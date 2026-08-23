import re

import discord
from discord.ext import commands

TAMANHO_MAXIMO = 256 * 1024
LIMITE_EMOJIS = 15

SCHEMA = """
CREATE TABLE IF NOT EXISTS emoji_imagem_contador (
    guild_id INTEGER PRIMARY KEY,
    total INTEGER NOT NULL DEFAULT 0
)
"""


def nome_emoji(filename: str) -> str:
    base = filename.rsplit(".", 1)[0]
    base = re.sub(r"[^a-zA-Z0-9_]", "", base)
    if len(base) < 2:
        base = (base + "emoji")[:2]
    return base[:32]


class EmojiImagem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.db.executescript(SCHEMA)
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO emoji_imagem_contador (guild_id, total) VALUES (?, 0)",
            (self.bot.config["guild_id"],),
        )
        await self.bot.db.commit()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if message.guild.id != self.bot.config["guild_id"]:
            return

        anexo = next((a for a in message.attachments if a.content_type and a.content_type.startswith("image/")), None)
        if anexo is None:
            return

        if anexo.size > TAMANHO_MAXIMO:
            await message.reply("Essa imagem passa de 256KB, o Discord nao aceita como emoji.", mention_author=False)
            return

        if not message.guild.me.guild_permissions.manage_emojis_and_stickers:
            await message.reply("Nao tenho permissao de gerenciar emojis nesse servidor.", mention_author=False)
            return

        cursor = await self.bot.db.execute(
            "UPDATE emoji_imagem_contador SET total = total + 1 WHERE guild_id = ? AND total < ?",
            (message.guild.id, LIMITE_EMOJIS),
        )
        await self.bot.db.commit()
        if cursor.rowcount == 0:
            await message.reply(f"Limite de {LIMITE_EMOJIS} emojis gerados ja foi atingido.", mention_author=False)
            return

        try:
            dados = await anexo.read()
            nome = nome_emoji(anexo.filename)
            emoji = await message.guild.create_custom_emoji(
                name=nome, image=dados, reason=f"gerado a partir de imagem de {message.author}"
            )
        except discord.HTTPException as erro:
            await self.bot.db.execute(
                "UPDATE emoji_imagem_contador SET total = total - 1 WHERE guild_id = ?", (message.guild.id,)
            )
            await self.bot.db.commit()
            await message.reply(f"Nao rolou criar o emoji: {erro}", mention_author=False)
            return

        async with self.bot.db.execute(
            "SELECT total FROM emoji_imagem_contador WHERE guild_id = ?", (message.guild.id,)
        ) as cursor:
            (total,) = await cursor.fetchone()

        await message.reply(
            f"Emoji criado: {emoji}\n"
            f"Nome: `{emoji.name}`\n"
            f"ID: `{emoji.id}`\n"
            f"Animado: {'sim' if emoji.animated else 'nao'}\n"
            f"URL: {emoji.url}\n"
            f"Contador: {total}/{LIMITE_EMOJIS}",
            mention_author=False,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EmojiImagem(bot))
