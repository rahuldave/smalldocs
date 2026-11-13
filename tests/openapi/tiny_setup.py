"The setup functions of the OpenAPI tests: each adds a router to the tiny app, as an app's lifespan does."

from fastapi import APIRouter, FastAPI

router = APIRouter(prefix="/api/teams", tags=["Teams"])


@router.get("")
def list_teams() -> list[str]:
    "List the teams."
    return []


def add_teams(
    app: FastAPI,  # The app
) -> None:
    "Add the router of teams."
    app.include_router(router)


async def add_teams_later(
    app: FastAPI,  # The app
) -> None:
    "Add the router of teams, as an `async def` setup."
    app.include_router(router)


def broken(
    app: FastAPI,  # The app
) -> None:
    "Fail, as a setup that needs a database fails."
    raise RuntimeError("no database")


NOT_CALLABLE = 3  # A name that is no function
