from fastmcp import FastMCP
import asyncpg
import json
import os
import ssl

mcp = FastMCP("ExpenseTracker")

CATEGORIES_PATH = os.path.join(
    os.path.dirname(__file__),
    "categories.json"
)

# --------------------------------------------------
# Database
# --------------------------------------------------

pool = None

async def get_pool():
    global pool

    if pool is None:
        # Fetch the environment variable AT RUNTIME, not at import time
        db_url = os.getenv("DATABASE_URL")
        
        if not db_url:
            raise ValueError("DATABASE_URL environment variable is missing!")

        # Establish an SSL context. Most cloud databases (Neon, Supabase, RDS)
        # require an encrypted connection and will reject you otherwise.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        pool = await asyncpg.create_pool(db_url, ssl=ctx)

        async with pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS expenses (
                    id SERIAL PRIMARY KEY,
                    date DATE NOT NULL,
                    amount NUMERIC NOT NULL,
                    category TEXT NOT NULL,
                    subcategory TEXT NOT NULL,
                    note TEXT DEFAULT ''
                )
                """
            )

    return pool

# --------------------------------------------------
# Validation
# --------------------------------------------------

def validate_category(category: str, subcategory: str) -> bool:
    try:
        with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        for item in data.get("categories", []):
            if item["name"] == category:
                return subcategory in item["subcategories"]

        return False

    except Exception:
        return False

# --------------------------------------------------
# Tools
# --------------------------------------------------

@mcp.tool()
async def add_expense(
    date: str,
    amount: float,
    category: str,
    subcategory: str,
    note: str = ""
):
    if not validate_category(category, subcategory):
        return {
            "status": "error",
            "message": "Invalid category/subcategory"
        }

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            expense_id = await conn.fetchval(
                """
                INSERT INTO expenses(
                    date, amount, category, subcategory, note
                )
                VALUES($1, $2, $3, $4, $5)
                RETURNING id
                """,
                date, amount, category, subcategory, note
            )

        return {
            "status": "success",
            "expense_id": expense_id
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@mcp.tool()
async def list_expenses(
    start_date: str,
    end_date: str
):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT *
                FROM expenses
                WHERE date BETWEEN $1 AND $2
                ORDER BY date DESC
                """,
                start_date, end_date
            )

        # Convert asyncpg Decimals to floats and Dates to strings for JSON serialization
        return [
            {
                "id": row["id"],
                "date": str(row["date"]),
                "amount": float(row["amount"]),
                "category": row["category"],
                "subcategory": row["subcategory"],
                "note": row["note"]
            }
            for row in rows
        ]

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@mcp.tool()
async def summarize(
    start_date: str,
    end_date: str,
    category: str | None = None
):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            if category:
                rows = await conn.fetch(
                    """
                    SELECT category, SUM(amount) AS total_amount, COUNT(*) AS count
                    FROM expenses
                    WHERE date BETWEEN $1 AND $2 AND category = $3
                    GROUP BY category
                    """,
                    start_date, end_date, category
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT category, SUM(amount) AS total_amount, COUNT(*) AS count
                    FROM expenses
                    WHERE date BETWEEN $1 AND $2
                    GROUP BY category
                    ORDER BY total_amount DESC
                    """,
                    start_date, end_date
                )

        # Convert asyncpg Decimals to floats for JSON serialization
        summary = [
            {
                "category": row["category"],
                "total_amount": float(row["total_amount"]),
                "count": row["count"]
            }
            for row in rows
        ]

        grand_total = sum(item["total_amount"] for item in summary)

        return {
            "summary": summary,
            "grand_total": grand_total
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@mcp.tool()
async def total_expenses(
    start_date: str,
    end_date: str
):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            total = await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM expenses
                WHERE date BETWEEN $1 AND $2
                """,
                start_date, end_date
            )

        # Convert asyncpg Decimal to float
        return {
            "total": float(total)
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@mcp.tool()
async def delete_expense(
    expense_id: int
):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM expenses
                WHERE id = $1
                """,
                expense_id
            )

        return {
            "status": "success",
            "message": f"Deleted expense {expense_id}"
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@mcp.tool()
async def health_check():
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            version = await conn.fetchval("SELECT version()")

        return {
            "status": "healthy",
            "database": "connected",
            "postgres": version
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

# --------------------------------------------------
# Resource
# --------------------------------------------------

@mcp.resource(
    "expense:///categories",
    mime_type="application/json"
)
def categories():
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        return f.read()

# --------------------------------------------------
# Server
# --------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))

    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=port
    )