from fastmcp import FastMCP
import os
import json
import sqlite3
import aiosqlite
import tempfile

# --------------------------------------------------
# Configuration
# --------------------------------------------------

TEMP_DIR = tempfile.gettempdir()

DB_PATH = os.path.join(
    TEMP_DIR,
    "expenses.db"
)

CATEGORIES_PATH = os.path.join(
    os.path.dirname(__file__),
    "categories.json"
)

mcp = FastMCP("ExpenseTracker")

# --------------------------------------------------
# Database Initialization
# --------------------------------------------------


def init_db():

    with sqlite3.connect(DB_PATH) as conn:

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT NOT NULL,
                note TEXT DEFAULT ''
            )
            """
        )

        conn.commit()


init_db()

# --------------------------------------------------
# Category Validation
# --------------------------------------------------


def validate_category(
    category: str,
    subcategory: str
) -> bool:

    try:

        with open(
            CATEGORIES_PATH,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        for item in data["categories"]:

            if item["name"] == category:

                return (
                    subcategory
                    in item["subcategories"]
                )

        return False

    except Exception:

        return False


# --------------------------------------------------
# MCP Tools
# --------------------------------------------------


@mcp.tool()
async def add_expense(
    date: str,
    amount: float,
    category: str,
    subcategory: str,
    note: str = ""
):
    """
    Add a new expense.
    """

    if not validate_category(
        category,
        subcategory
    ):

        return {
            "status": "error",
            "message":
            "Invalid category/subcategory."
        }

    try:

        async with aiosqlite.connect(
            DB_PATH
        ) as conn:

            cur = await conn.execute(
                """
                INSERT INTO expenses(
                    date,
                    amount,
                    category,
                    subcategory,
                    note
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    date,
                    amount,
                    category,
                    subcategory,
                    note
                )
            )

            await conn.commit()

            return {
                "status": "success",
                "expense_id": cur.lastrowid
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
    """
    List expenses between two dates.
    """

    try:

        async with aiosqlite.connect(
            DB_PATH
        ) as conn:

            cur = await conn.execute(
                """
                SELECT
                    id,
                    date,
                    amount,
                    category,
                    subcategory,
                    note
                FROM expenses
                WHERE date BETWEEN ? AND ?
                ORDER BY date DESC
                """,
                (
                    start_date,
                    end_date
                )
            )

            rows = await cur.fetchall()

            columns = [
                d[0]
                for d in cur.description
            ]

            return [
                dict(zip(columns, row))
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
    """
    Summarize expenses.
    """

    try:

        query = """
            SELECT
                category,
                SUM(amount) AS total_amount,
                COUNT(*) AS count
            FROM expenses
            WHERE date BETWEEN ? AND ?
        """

        params = [
            start_date,
            end_date
        ]

        if category:

            query += """
                AND category = ?
            """

            params.append(category)

        query += """
            GROUP BY category
            ORDER BY total_amount DESC
        """

        async with aiosqlite.connect(
            DB_PATH
        ) as conn:

            cur = await conn.execute(
                query,
                params
            )

            rows = await cur.fetchall()

            columns = [
                d[0]
                for d in cur.description
            ]

            summary = [
                dict(zip(columns, row))
                for row in rows
            ]

            grand_total = sum(
                item["total_amount"]
                for item in summary
            )

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
    """
    Get total expenses.
    """

    try:

        async with aiosqlite.connect(
            DB_PATH
        ) as conn:

            cur = await conn.execute(
                """
                SELECT
                    COALESCE(
                        SUM(amount),
                        0
                    )
                FROM expenses
                WHERE date BETWEEN ? AND ?
                """,
                (
                    start_date,
                    end_date
                )
            )

            row = await cur.fetchone()
            total = row[0] if row is not None else 0

            return {
                "total": total
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
    """
    Delete an expense.
    """

    try:

        async with aiosqlite.connect(
            DB_PATH
        ) as conn:

            await conn.execute(
                """
                DELETE FROM expenses
                WHERE id = ?
                """,
                (expense_id,)
            )

            await conn.commit()

            return {
                "status": "success",
                "message":
                f"Deleted expense {expense_id}"
            }

    except Exception as e:

        return {
            "status": "error",
            "message": str(e)
        }


# --------------------------------------------------
# MCP Resource
# --------------------------------------------------


@mcp.resource(
    "expense:///categories",
    mime_type="application/json"
)
def categories():

    with open(
        CATEGORIES_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        return f.read()


# --------------------------------------------------
# Run Server
# --------------------------------------------------

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            8000
        )
    )

    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=port
    )