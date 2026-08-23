import asyncio
import os
import sqlite3
import sys
from pathlib import Path

import aiosqlite
import discord
import yaml
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

CONFIG_PATH = Path("config/config.yaml")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER,
    user_id INTEGER NOT NULL,
    categoria TEXT NOT NULL,
    assunto TEXT NOT NULL,
    descricao TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'aberto',
    criado_em TEXT NOT NULL,
    fechado_em TEXT,
    transcricao TEXT
);

CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    valor TEXT NOT NULL,
    label TEXT NOT NULL,
    emoji TEXT,
    posicao INTEGER NOT NULL,
    UNIQUE(guild_id, valor)
);

CREATE TABLE IF NOT EXISTS painel_config (
    guild_id INTEGER PRIMARY KEY,
    titulo TEXT NOT NULL,
    descricao TEXT NOT NULL,
    cor INTEGER NOT NULL,
    fechar_label TEXT NOT NULL,
    fechar_emoji TEXT,
    assumir_label TEXT NOT NULL,
    assumir_emoji TEXT
)
"""


def carregar_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.exit(f"config nao encontrado em {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        try:
            config = yaml.safe_load(f)
        except yaml.YAMLError as erro:
            sys.exit(f"config.yaml com erro de sintaxe: {erro}")
    if not isinstance(config, dict):
        sys.exit("config invalido")
    if not config.get("guild_id"):
        sys.exit("guild_id nao definido no config.yaml")
    return config


class TicketBot(commands.Bot):
    def __init__(self, config: dict):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.config = config
        self.db: aiosqlite.Connection | None = None

    async def setup_hook(self):
        banco_cfg = self.config.get("banco", {})
        caminho = Path(banco_cfg.get("caminho", "data/tickets.db"))
        if banco_cfg.get("criar_pasta", True):
            await asyncio.to_thread(caminho.parent.mkdir, parents=True, exist_ok=True)
        elif not caminho.parent.is_dir():
            sys.exit(f"pasta {caminho.parent} nao existe")

        self.db = await aiosqlite.connect(caminho)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.executescript(SCHEMA)

        colunas_novas = {
            "tickets": {"assumido_por": "INTEGER"},
            "painel_config": {
                "staff_role_id": "INTEGER",
                "log_channel_id": "INTEGER",
                "categoria_tickets_id": "INTEGER",
                "limite_por_usuario": "INTEGER NOT NULL DEFAULT 0",
                "boas_vindas": "TEXT NOT NULL DEFAULT '{mention} abriu um ticket.'",
            },
        }
        for tabela, colunas in colunas_novas.items():
            for coluna, tipo in colunas.items():
                try:
                    await self.db.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
                except sqlite3.OperationalError as erro:
                    if "duplicate column name" not in str(erro):
                        raise
        await self.db.commit()

        await self.load_extension("cogs.tickets")
        await self.load_extension("cogs.emoji_imagem")

        guild = discord.Object(id=self.config["guild_id"])
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def close(self):
        if self.db is not None:
            await self.db.close()
        await super().close()


def main():
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        sys.exit("DISCORD_TOKEN nao definido no .env")

    config = carregar_config()
    bot = TicketBot(config)

    @bot.tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "voce nao tem permissao pra isso."
        else:
            msg = "deu erro ao processar o comando."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    async def runner():
        async with bot:
            await bot.start(token)

    asyncio.run(runner())


if __name__ == "__main__":
    main()
