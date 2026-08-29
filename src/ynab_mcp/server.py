"""
Custom YNAB MCP server.

Talks directly to YNAB's REST API (https://api.ynab.com/v1) rather than
wrapping a third-party SDK or MCP project, so there's nothing here beyond
what this file does. Read + write scope: can view budgets/accounts/
categories/transactions/month summaries, and create transactions (including
splits), approve/edit them, and assign money to categories.

Runs over stdio — this is a local process your MCP client (Claude Desktop,
Claude Code, Cowork) launches itself and talks to directly, not a hosted
server. No networking, no Docker, no shared instance across machines: each
machine running this needs its own YNAB_ACCESS_TOKEN set in its own client
config.

Env vars:
  YNAB_ACCESS_TOKEN     - required. Personal Access Token from
                          https://app.ynab.com/settings/developer
  YNAB_DEFAULT_BUDGET_ID - optional. See "Budget selection" below.

Budget selection: every tool takes an optional budget_id, defaulting to
YNAB's special "last-used" value, which is almost always what you want for
a single-budget household. Pass a specific budget_id (from list_budgets)
if you manage more than one, or set YNAB_DEFAULT_BUDGET_ID to pin one
without having to pass it on every call.

Amounts: exposed to the caller in plain dollars (e.g. 12.34). YNAB's API
itself uses "milliunits" (12.34 -> 12340) internally; conversion happens
at the edges in _to_milliunits / _from_milliunits.
"""

import logging
import os
import sys
from typing import Any, Optional

import httpx
from fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,  # stdout is the MCP protocol channel under stdio transport — never log there
)
log = logging.getLogger("ynab-mcp")

YNAB_BASE_URL = "https://api.ynab.com/v1"


def _to_milliunits(dollars: float) -> int:
    return int(round(dollars * 1000))


def _from_milliunits(milliunits: int) -> float:
    return round(milliunits / 1000.0, 2)


def _summarize_transaction(t: dict) -> dict:
    summary = {
        "id": t.get("id"),
        "date": t.get("date"),
        "amount": _from_milliunits(t.get("amount", 0)),
        "payee_name": t.get("payee_name"),
        "category_name": t.get("category_name"),
        "account_name": t.get("account_name"),
        "memo": t.get("memo"),
        "cleared": t.get("cleared"),
        "approved": t.get("approved"),
        "deleted": t.get("deleted", False),
    }
    subs = [s for s in t.get("subtransactions", []) if not s.get("deleted")]
    if subs:
        summary["subtransactions"] = [
            {
                "id": s.get("id"),
                "amount": _from_milliunits(s.get("amount", 0)),
                "category_id": s.get("category_id"),
                "category_name": s.get("category_name"),
                "memo": s.get("memo"),
            }
            for s in subs
        ]
    return summary


class YnabClient:
    def __init__(self, token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=YNAB_BASE_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )

    async def request(self, method: str, path: str, **kwargs) -> dict:
        resp = await self._client.request(method, path, **kwargs)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"YNAB API error {resp.status_code} on {method} {path}: {resp.text}"
            )
        if resp.status_code == 204:
            return {}
        return resp.json().get("data", {})


def create_server() -> FastMCP:
    token = os.environ.get("YNAB_ACCESS_TOKEN", "")
    if not token:
        log.error("YNAB_ACCESS_TOKEN is required.")
        sys.exit(1)

    # "last-used" tracks whatever budget was last opened in the YNAB app or
    # web UI, which drifts if you ever browse a different budget there. Set
    # YNAB_DEFAULT_BUDGET_ID (get the id from list_budgets) to pin a specific
    # budget instead, if you have more than one.
    default_budget = os.environ.get("YNAB_DEFAULT_BUDGET_ID", "last-used")

    ynab = YnabClient(token)
    mcp = FastMCP("ynab-mcp")

    @mcp.tool()
    async def list_budgets() -> list[dict]:
        """List all YNAB budgets available to this account."""
        data = await ynab.request("GET", "/budgets")
        return [
            {"id": b["id"], "name": b["name"], "currency": b.get("currency_format", {}).get("iso_code")}
            for b in data.get("budgets", [])
        ]

    @mcp.tool()
    async def list_accounts(budget_id: str = default_budget) -> list[dict]:
        """List accounts in a budget, with current balances in dollars."""
        data = await ynab.request("GET", f"/budgets/{budget_id}/accounts")
        return [
            {
                "id": a["id"],
                "name": a["name"],
                "type": a["type"],
                "balance": _from_milliunits(a["balance"]),
                "closed": a["closed"],
            }
            for a in data.get("accounts", [])
            if not a.get("deleted")
        ]

    @mcp.tool()
    async def list_categories(budget_id: str = default_budget) -> list[dict]:
        """List budget categories grouped by category group, with budgeted,
        activity, and balance amounts in dollars for the current month."""
        data = await ynab.request("GET", f"/budgets/{budget_id}/categories")
        result = []
        for group in data.get("category_groups", []):
            if group.get("deleted") or group.get("hidden"):
                continue
            for cat in group.get("categories", []):
                if cat.get("deleted") or cat.get("hidden"):
                    continue
                result.append(
                    {
                        "id": cat["id"],
                        "name": cat["name"],
                        "category_group": group["name"],
                        "budgeted": _from_milliunits(cat["budgeted"]),
                        "activity": _from_milliunits(cat["activity"]),
                        "balance": _from_milliunits(cat["balance"]),
                    }
                )
        return result

    @mcp.tool()
    async def get_month(month: str = "current", budget_id: str = default_budget) -> dict:
        """Get overall budget status for a month: income, total budgeted,
        total activity, Ready to Assign, and age of money. month is
        YYYY-MM-01 or the literal "current"."""
        data = await ynab.request("GET", f"/budgets/{budget_id}/months/{month}")
        m = data.get("month", {})
        return {
            "month": m.get("month"),
            "income": _from_milliunits(m.get("income", 0)),
            "budgeted": _from_milliunits(m.get("budgeted", 0)),
            "activity": _from_milliunits(m.get("activity", 0)),
            "ready_to_assign": _from_milliunits(m.get("to_be_budgeted", 0)),
            "age_of_money": m.get("age_of_money"),
        }

    @mcp.tool()
    async def get_unapproved_transactions(budget_id: str = default_budget) -> list[dict]:
        """List transactions awaiting approval (e.g. pulled in via bank sync)."""
        data = await ynab.request(
            "GET", f"/budgets/{budget_id}/transactions", params={"type": "unapproved"}
        )
        return [_summarize_transaction(t) for t in data.get("transactions", []) if not t.get("deleted")]

    @mcp.tool()
    async def list_transactions(
        budget_id: str = default_budget,
        since_date: Optional[str] = None,
        account_id: Optional[str] = None,
        category_id: Optional[str] = None,
    ) -> list[dict]:
        """List transactions, optionally filtered by an account, a category,
        and/or a start date (YYYY-MM-DD)."""
        if account_id:
            path = f"/budgets/{budget_id}/accounts/{account_id}/transactions"
        elif category_id:
            path = f"/budgets/{budget_id}/categories/{category_id}/transactions"
        else:
            path = f"/budgets/{budget_id}/transactions"
        params = {"since_date": since_date} if since_date else {}
        data = await ynab.request("GET", path, params=params)
        return [_summarize_transaction(t) for t in data.get("transactions", []) if not t.get("deleted")]

    @mcp.tool()
    async def create_transaction(
        account_id: str,
        date: str,
        amount: float,
        budget_id: str = default_budget,
        payee_name: Optional[str] = None,
        category_id: Optional[str] = None,
        memo: Optional[str] = None,
        cleared: str = "uncleared",
        approved: bool = False,
        import_id: Optional[str] = None,
        subtransactions: Optional[list[dict]] = None,
    ) -> dict:
        """Create a new transaction. amount is in dollars, negative for an
        outflow (a normal purchase) and positive for an inflow (income/refund).
        date is YYYY-MM-DD. cleared is one of: cleared, uncleared, reconciled.

        Pass import_id (any string you generate, e.g. a hash of the request)
        to make retries safe — YNAB rejects an exact repeat with the same
        import_id instead of creating a duplicate.

        Pass subtransactions to create a split transaction instead of a
        plain one — omit category_id in that case. Each subtransaction dict
        needs amount (dollars, must sum exactly to the parent amount) plus
        category_id and optionally memo."""
        body = {
            "transaction": {
                "account_id": account_id,
                "date": date,
                "amount": _to_milliunits(amount),
                "cleared": cleared,
                "approved": approved,
            }
        }
        if payee_name:
            body["transaction"]["payee_name"] = payee_name
        if category_id:
            body["transaction"]["category_id"] = category_id
        if memo:
            body["transaction"]["memo"] = memo
        if import_id:
            body["transaction"]["import_id"] = import_id
        if subtransactions:
            total = sum(s["amount"] for s in subtransactions)
            if round(total, 2) != round(amount, 2):
                raise ValueError(
                    f"subtransactions sum to {total}, must equal parent amount {amount}"
                )
            body["transaction"]["subtransactions"] = [
                {
                    "amount": _to_milliunits(s["amount"]),
                    "category_id": s.get("category_id"),
                    "memo": s.get("memo"),
                }
                for s in subtransactions
            ]
        data = await ynab.request("POST", f"/budgets/{budget_id}/transactions", json=body)
        return _summarize_transaction(data.get("transaction", {}))

    @mcp.tool()
    async def approve_transaction(transaction_id: str, budget_id: str = default_budget) -> dict:
        """Mark an existing transaction as approved (e.g. after reviewing a
        bank-synced transaction from get_unapproved_transactions)."""
        body = {"transaction": {"approved": True}}
        data = await ynab.request(
            "PATCH", f"/budgets/{budget_id}/transactions/{transaction_id}", json=body
        )
        return _summarize_transaction(data.get("transaction", {}))

    @mcp.tool()
    async def update_transaction(
        transaction_id: str,
        budget_id: str = default_budget,
        amount: Optional[float] = None,
        payee_name: Optional[str] = None,
        category_id: Optional[str] = None,
        memo: Optional[str] = None,
        cleared: Optional[str] = None,
        approved: Optional[bool] = None,
        date: Optional[str] = None,
        subtransactions: Optional[list[dict]] = None,
    ) -> dict:
        """Update fields on an existing transaction. Only pass the fields you
        want to change; everything else is left as-is.

        Pass subtransactions to turn this transaction into a split (or
        replace its existing split) — omit category_id in that case. Each
        subtransaction dict needs amount (dollars, must sum exactly to the
        transaction's total amount — pass amount too if you're not sure what
        the current total is) plus category_id and optionally memo. This
        relies on YNAB's update endpoint accepting subtransactions the same
        way create does; unverified until actually tried."""
        fields: dict[str, Any] = {}
        if amount is not None:
            fields["amount"] = _to_milliunits(amount)
        if payee_name is not None:
            fields["payee_name"] = payee_name
        if category_id is not None:
            fields["category_id"] = category_id
        if memo is not None:
            fields["memo"] = memo
        if cleared is not None:
            fields["cleared"] = cleared
        if approved is not None:
            fields["approved"] = approved
        if date is not None:
            fields["date"] = date
        if subtransactions:
            if category_id is None:
                # A transaction being converted to a split shouldn't keep its
                # old single category — clear it explicitly, since YNAB won't
                # infer that from the presence of subtransactions alone.
                fields["category_id"] = None
            if amount is None:
                # Need the parent total to validate against; fetch it if not given.
                current = await ynab.request(
                    "GET", f"/budgets/{budget_id}/transactions/{transaction_id}"
                )
                parent_amount = _from_milliunits(current.get("transaction", {}).get("amount", 0))
            else:
                parent_amount = amount
            total = sum(s["amount"] for s in subtransactions)
            if round(total, 2) != round(parent_amount, 2):
                raise ValueError(
                    f"subtransactions sum to {total}, must equal transaction amount {parent_amount}"
                )
            fields["subtransactions"] = [
                {
                    "amount": _to_milliunits(s["amount"]),
                    "category_id": s.get("category_id"),
                    "memo": s.get("memo"),
                }
                for s in subtransactions
            ]
        data = await ynab.request(
            "PATCH",
            f"/budgets/{budget_id}/transactions/{transaction_id}",
            json={"transaction": fields},
        )
        return _summarize_transaction(data.get("transaction", {}))

    # Disabled for now — see conversation history. To re-enable, uncomment
    # the block below.
    # @mcp.tool()
    # async def delete_transaction(transaction_id: str, budget_id: str = default_budget) -> dict:
    #     """Permanently delete a transaction. No undo."""
    #     data = await ynab.request(
    #         "DELETE", f"/budgets/{budget_id}/transactions/{transaction_id}"
    #     )
    #     return _summarize_transaction(data.get("transaction", {}))

    @mcp.tool()
    async def assign_to_category(
        category_id: str,
        budgeted_amount: float,
        month: str = "current",
        budget_id: str = default_budget,
    ) -> dict:
        """Set the budgeted (assigned) amount for a category in a given month.
        month is YYYY-MM-01 or the literal "current". budgeted_amount is the
        total assigned for that category that month, in dollars (not a delta)."""
        body = {"category": {"budgeted": _to_milliunits(budgeted_amount)}}
        data = await ynab.request(
            "PATCH",
            f"/budgets/{budget_id}/months/{month}/categories/{category_id}",
            json=body,
        )
        cat = data.get("category", {})
        return {
            "id": cat.get("id"),
            "name": cat.get("name"),
            "budgeted": _from_milliunits(cat.get("budgeted", 0)),
            "activity": _from_milliunits(cat.get("activity", 0)),
            "balance": _from_milliunits(cat.get("balance", 0)),
        }

    return mcp


def main() -> None:
    log.info("-----------------------------------------------------------")
    log.info("ynab-mcp starting (stdio)")
    log.info("-----------------------------------------------------------")

    mcp = create_server()
    mcp.run()  # defaults to stdio transport


if __name__ == "__main__":
    main()
