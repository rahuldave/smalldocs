"A tiny FastAPI app for the OpenAPI tests: a path, a query and a header parameter, a body, a response model and a tag."

from typing import Annotated

from fastapi import FastAPI, Header, Path, Query
from pydantic import BaseModel, Field

app = FastAPI(title="Tiny", version="0.1.0", description="A tiny API of players.")


class Player(BaseModel):
    "A player."

    id: str = Field(description="The cricsheet id")
    name: str = Field(description="The full name")
    team: str | None = Field(None, description="The current team, if any")


class NewPlayer(BaseModel):
    "The fields to make a player."

    name: str = Field(description="The full name")


@app.get("/api/players/{player_id}", tags=["Players"], response_model=Player)
def get_player(
    player_id: Annotated[str, Path(description="The player's id")],
    season: Annotated[str | None, Query(description="Only this season")] = None,
    limit: Annotated[int, Query(description="At most this many rows", ge=1)] = 10,
    x_trace: Annotated[str | None, Header(description="A trace id")] = None,
) -> Player:
    "Get one player."


@app.post("/api/players", tags=["Players"], status_code=201)
def make_player(body: NewPlayer) -> Player:
    "Make a player."
