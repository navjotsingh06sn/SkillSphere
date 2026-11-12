
import asyncio
from sqlalchemy import text
from app.db import engine


async def test_connection():
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT current_database()")
            )

            print("Connected successfully!")
            print("Database:", result.scalar())

    except Exception as error:
        print("Connection failed!")
        print(error)

    finally:
        await engine.dispose()


asyncio.run(test_connection())
