import asyncio
import sqlite3
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

CATEGORIAS_PADRAO = (
    ("suporte", "Suporte tecnico", None),
    ("financeiro", "Financeiro", None),
    ("duvida", "Duvida geral", None),
)

TITULO_PADRAO = "Central de atendimento"
DESCRICAO_PADRAO = "Escolha o motivo abaixo pra abrir um ticket."
COR_PADRAO = 0x5865F2
FECHAR_LABEL_PADRAO = "Fechar ticket"
ASSUMIR_LABEL_PADRAO = "Assumir ticket"
BOAS_VINDAS_PADRAO = "{mention} abriu um ticket."


def parse_emoji(valor: str | None) -> discord.PartialEmoji | None:
    if not valor:
        return None
    return discord.PartialEmoji.from_str(valor)


def formatar_resumo(config: dict, total_categorias: int) -> str:
    staff = f"<@&{config['staff_role_id']}>" if config["staff_role_id"] else "nao definido"
    log = f"<#{config['log_channel_id']}>" if config["log_channel_id"] else "nao definido"
    categoria_tickets = f"<#{config['categoria_tickets_id']}>" if config["categoria_tickets_id"] else "nao definida"
    limite = config["limite_por_usuario"] or "sem limite"
    return (
        f"Titulo: {config['titulo']}\n"
        f"Categorias cadastradas: {total_categorias}\n"
        f"Cargo staff: {staff}\n"
        f"Canal de log: {log}\n"
        f"Categoria dos tickets: {categoria_tickets}\n"
        f"Limite por pessoa: {limite}"
    )


class CategoriaSelect(discord.ui.Select):
    def __init__(self, categorias):
        super().__init__(
            custom_id="ticket:categoria",
            placeholder="Selecione o motivo do contato",
            options=[
                discord.SelectOption(label=label, value=valor, emoji=parse_emoji(emoji))
                for valor, label, emoji in categorias
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TicketModal(categoria=self.values[0]))


class PainelRow(discord.ui.ActionRow):
    def __init__(self, categorias):
        super().__init__()
        self.add_item(CategoriaSelect(categorias))


class PainelView(discord.ui.LayoutView):
    def __init__(self, titulo, descricao, cor, categorias):
        super().__init__(timeout=None)
        container = discord.ui.Container(
            discord.ui.TextDisplay(f"## {titulo}"),
            discord.ui.TextDisplay(descricao),
            discord.ui.Separator(),
            PainelRow(categorias),
            accent_color=discord.Color(cor),
        )
        self.add_item(container)


class TicketModal(discord.ui.Modal, title="Abrir ticket"):
    assunto = discord.ui.TextInput(label="Assunto", max_length=80)
    descricao = discord.ui.TextInput(
        label="Descreva a situacao",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    def __init__(self, categoria: str):
        super().__init__()
        self.categoria = categoria

    async def on_submit(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Tickets")
        await cog.criar_ticket(interaction, self.categoria, self.assunto.value, self.descricao.value)


class FecharButton(discord.ui.Button):
    def __init__(self, label, emoji):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.danger,
            custom_id="ticket:fechar",
            emoji=parse_emoji(emoji),
        )

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Tickets")
        await cog.fechar_ticket(interaction)


class AssumirButton(discord.ui.Button):
    def __init__(self, label, emoji):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary,
            custom_id="ticket:assumir",
            emoji=parse_emoji(emoji),
        )

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Tickets")
        await cog.assumir_ticket(interaction)


class AcoesRow(discord.ui.ActionRow):
    def __init__(
        self,
        assumir_label=ASSUMIR_LABEL_PADRAO,
        assumir_emoji=None,
        fechar_label=FECHAR_LABEL_PADRAO,
        fechar_emoji=None,
    ):
        super().__init__()
        self.add_item(AssumirButton(assumir_label, assumir_emoji))
        self.add_item(FecharButton(fechar_label, fechar_emoji))


class AcoesView(discord.ui.LayoutView):
    def __init__(self, *args, **kwargs):
        super().__init__(timeout=None)
        self.add_item(AcoesRow(*args, **kwargs))


class TextosModal(discord.ui.Modal):
    def __init__(self, cog: "Tickets", config: dict):
        super().__init__(title="Editar textos do painel")
        self.cog = cog
        self.titulo = discord.ui.TextInput(label="Titulo", default=config["titulo"], max_length=100)
        self.descricao = discord.ui.TextInput(
            label="Descricao", style=discord.TextStyle.paragraph, default=config["descricao"], max_length=300
        )
        self.cor = discord.ui.TextInput(label="Cor hex (ex: 5865F2)", default=f"{config['cor']:06X}", max_length=7)
        self.boas_vindas = discord.ui.TextInput(
            label="Mensagem ao abrir (use {mention})",
            style=discord.TextStyle.paragraph,
            default=config["boas_vindas"],
            max_length=300,
        )
        for item in (self.titulo, self.descricao, self.cor, self.boas_vindas):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cor = int(self.cor.value.lstrip("#"), 16)
        except ValueError:
            await interaction.response.send_message("Cor invalida, manda um hex tipo 5865F2.", ephemeral=True)
            return
        await self.cog.atualizar_config(
            interaction.guild_id,
            {
                "titulo": self.titulo.value,
                "descricao": self.descricao.value,
                "cor": cor,
                "boas_vindas": self.boas_vindas.value,
            },
        )
        await interaction.response.send_message(
            "Textos atualizados. Roda /ticket-painel de novo pra republicar.", ephemeral=True
        )


class BotoesModal(discord.ui.Modal):
    def __init__(self, cog: "Tickets", config: dict):
        super().__init__(title="Editar botoes do ticket")
        self.cog = cog
        self.fechar_label = discord.ui.TextInput(label="Texto do botao Fechar", default=config["fechar_label"], max_length=80)
        self.fechar_emoji = discord.ui.TextInput(
            label="Emoji do botao Fechar (opcional)", required=False, default=config["fechar_emoji"] or "", max_length=60
        )
        self.assumir_label = discord.ui.TextInput(
            label="Texto do botao Assumir", default=config["assumir_label"], max_length=80
        )
        self.assumir_emoji = discord.ui.TextInput(
            label="Emoji do botao Assumir (opcional)", required=False, default=config["assumir_emoji"] or "", max_length=60
        )
        for item in (self.fechar_label, self.fechar_emoji, self.assumir_label, self.assumir_emoji):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.atualizar_config(
            interaction.guild_id,
            {
                "fechar_label": self.fechar_label.value,
                "fechar_emoji": self.fechar_emoji.value or None,
                "assumir_label": self.assumir_label.value,
                "assumir_emoji": self.assumir_emoji.value or None,
            },
        )
        await interaction.response.send_message(
            "Botoes atualizados. Roda /ticket-painel de novo pra republicar.", ephemeral=True
        )


class LimiteModal(discord.ui.Modal):
    def __init__(self, cog: "Tickets", config: dict):
        super().__init__(title="Limite de tickets por pessoa")
        self.cog = cog
        self.limite = discord.ui.TextInput(
            label="Limite (0 = sem limite)", default=str(config["limite_por_usuario"]), max_length=3
        )
        self.add_item(self.limite)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            valor = int(self.limite.value)
            if valor < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Manda um numero inteiro maior ou igual a 0.", ephemeral=True)
            return
        await self.cog.atualizar_config(interaction.guild_id, {"limite_por_usuario": valor})
        await interaction.response.send_message("Limite atualizado.", ephemeral=True)


class CategoriaAddModal(discord.ui.Modal, title="Adicionar categoria"):
    valor = discord.ui.TextInput(label="Valor (slug interno)", max_length=32)
    label_exibido = discord.ui.TextInput(label="Nome exibido", max_length=100)
    emoji = discord.ui.TextInput(label="Emoji (opcional)", required=False, max_length=60)

    def __init__(self, cog: "Tickets"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        _, msg = await self.cog.categoria_add_db(
            interaction.guild_id, self.valor.value, self.label_exibido.value, self.emoji.value or None
        )
        await interaction.response.send_message(msg, ephemeral=True)


class RemoverCategoriaSelect(discord.ui.Select):
    def __init__(self, cog: "Tickets", categorias):
        super().__init__(
            placeholder="Selecione uma categoria pra remover",
            options=[
                discord.SelectOption(label=label, value=valor, emoji=parse_emoji(emoji))
                for valor, label, emoji in categorias
            ],
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        _, msg = await self.cog.categoria_remover_db(interaction.guild_id, self.values[0])
        await interaction.response.send_message(msg, ephemeral=True)


class CategoriasView(discord.ui.View):
    def __init__(self, cog: "Tickets", categorias):
        super().__init__(timeout=180)
        self.cog = cog
        if categorias:
            self.add_item(RemoverCategoriaSelect(cog, categorias))

    @discord.ui.button(label="Adicionar categoria", style=discord.ButtonStyle.success)
    async def adicionar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CategoriaAddModal(self.cog))


class CargosCanaisView(discord.ui.View):
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=180)
        self.cog = cog

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Cargo staff")
    async def staff(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        role = select.values[0]
        await self.cog.atualizar_config(interaction.guild_id, {"staff_role_id": role.id})
        await interaction.response.send_message(f"Cargo staff definido: {role.mention}", ephemeral=True)

    @discord.ui.select(cls=discord.ui.ChannelSelect, placeholder="Categoria dos tickets", channel_types=[discord.ChannelType.category])
    async def categoria_tickets(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        canal = select.values[0]
        await self.cog.atualizar_config(interaction.guild_id, {"categoria_tickets_id": canal.id})
        await interaction.response.send_message(f"Categoria dos tickets definida: {canal.mention}", ephemeral=True)

    @discord.ui.select(cls=discord.ui.ChannelSelect, placeholder="Canal de log", channel_types=[discord.ChannelType.text])
    async def log(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        canal = select.values[0]
        await self.cog.atualizar_config(interaction.guild_id, {"log_channel_id": canal.id})
        await interaction.response.send_message(f"Canal de log definido: {canal.mention}", ephemeral=True)


class DashboardRow1(discord.ui.ActionRow):
    def __init__(self, cog: "Tickets"):
        super().__init__()
        self.cog = cog

    @discord.ui.button(label="Editar textos", style=discord.ButtonStyle.primary)
    async def textos(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self.cog._get_painel_config(interaction.guild_id)
        await interaction.response.send_modal(TextosModal(self.cog, config))

    @discord.ui.button(label="Editar botoes", style=discord.ButtonStyle.primary)
    async def botoes(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self.cog._get_painel_config(interaction.guild_id)
        await interaction.response.send_modal(BotoesModal(self.cog, config))

    @discord.ui.button(label="Limite por pessoa", style=discord.ButtonStyle.primary)
    async def limite(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self.cog._get_painel_config(interaction.guild_id)
        await interaction.response.send_modal(LimiteModal(self.cog, config))


class DashboardRow2(discord.ui.ActionRow):
    def __init__(self, cog: "Tickets"):
        super().__init__()
        self.cog = cog

    @discord.ui.button(label="Gerenciar categorias", style=discord.ButtonStyle.secondary)
    async def categorias_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        categorias = await self.cog._get_categorias(interaction.guild_id)
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.followup.send(
                "Selecione uma categoria pra remover ou clique em adicionar:",
                view=CategoriasView(self.cog, categorias),
                ephemeral=True,
            )
        except discord.HTTPException:
            await interaction.followup.send(
                "Uma categoria tem emoji invalido configurado. Corrige com /ticket-config categoria-remover antes.",
                ephemeral=True,
            )

    @discord.ui.button(label="Cargos e canais", style=discord.ButtonStyle.secondary)
    async def cargos_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Escolha o cargo staff, a categoria dos tickets e o canal de log:",
            view=CargosCanaisView(self.cog),
            ephemeral=True,
        )

    @discord.ui.button(label="Publicar painel de tickets", style=discord.ButtonStyle.success)
    async def publicar(self, interaction: discord.Interaction, button: discord.ui.Button):
        _, msg = await self.cog.publicar_painel(interaction.guild_id, interaction.channel)
        await interaction.response.send_message(msg, ephemeral=True)


class DashboardView(discord.ui.LayoutView):
    def __init__(self, cog: "Tickets", config: dict, categorias):
        super().__init__(timeout=300)
        container = discord.ui.Container(
            discord.ui.TextDisplay("## Configuracao do sistema de tickets"),
            discord.ui.TextDisplay(formatar_resumo(config, len(categorias))),
            discord.ui.Separator(),
            DashboardRow1(cog),
            DashboardRow2(cog),
            accent_color=discord.Color(config["cor"]),
        )
        self.add_item(container)


class Tickets(commands.Cog):
    ticket_config = app_commands.Group(name="ticket-config", description="Configura o painel de tickets")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        guild_id = self.bot.config["guild_id"]
        await self._seed_padrao(guild_id)
        config = await self._get_painel_config(guild_id)
        categorias = await self._get_categorias(guild_id)
        self.bot.add_view(PainelView(config["titulo"], config["descricao"], config["cor"], categorias))
        self.bot.add_view(
            AcoesView(
                config["assumir_label"],
                config["assumir_emoji"],
                config["fechar_label"],
                config["fechar_emoji"],
            )
        )

    async def _seed_padrao(self, guild_id: int):
        db = self.bot.db
        cfg = self.bot.config

        async with db.execute("SELECT 1 FROM painel_config WHERE guild_id = ?", (guild_id,)) as cursor:
            existe = await cursor.fetchone()
        if existe is None:
            await db.execute(
                """INSERT INTO painel_config
                   (guild_id, titulo, descricao, cor, fechar_label, fechar_emoji, assumir_label, assumir_emoji,
                    staff_role_id, log_channel_id, categoria_tickets_id, limite_por_usuario, boas_vindas)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    guild_id,
                    TITULO_PADRAO,
                    DESCRICAO_PADRAO,
                    COR_PADRAO,
                    FECHAR_LABEL_PADRAO,
                    None,
                    ASSUMIR_LABEL_PADRAO,
                    None,
                    cfg.get("staff_role_id"),
                    cfg.get("log_channel_id"),
                    cfg.get("categoria_tickets_id"),
                    0,
                    BOAS_VINDAS_PADRAO,
                ),
            )
        else:
            await db.execute(
                """UPDATE painel_config SET
                       staff_role_id = COALESCE(staff_role_id, ?),
                       log_channel_id = COALESCE(log_channel_id, ?),
                       categoria_tickets_id = COALESCE(categoria_tickets_id, ?)
                   WHERE guild_id = ?""",
                (cfg.get("staff_role_id"), cfg.get("log_channel_id"), cfg.get("categoria_tickets_id"), guild_id),
            )

        async with db.execute("SELECT 1 FROM categorias WHERE guild_id = ?", (guild_id,)) as cursor:
            existe = await cursor.fetchone()
        if existe is None:
            for posicao, (valor, label, emoji) in enumerate(CATEGORIAS_PADRAO):
                await db.execute(
                    "INSERT INTO categorias (guild_id, valor, label, emoji, posicao) VALUES (?, ?, ?, ?, ?)",
                    (guild_id, valor, label, emoji, posicao),
                )
        await db.commit()

    async def _get_painel_config(self, guild_id: int) -> dict:
        async with self.bot.db.execute("SELECT * FROM painel_config WHERE guild_id = ?", (guild_id,)) as cursor:
            row = await cursor.fetchone()
        return dict(row)

    async def _get_categorias(self, guild_id: int) -> list:
        async with self.bot.db.execute(
            "SELECT valor, label, emoji FROM categorias WHERE guild_id = ? ORDER BY posicao", (guild_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [(r["valor"], r["label"], r["emoji"]) for r in rows]

    async def atualizar_config(self, guild_id: int, campos: dict):
        set_clause = ", ".join(f"{coluna} = ?" for coluna in campos)
        await self.bot.db.execute(
            f"UPDATE painel_config SET {set_clause} WHERE guild_id = ?",
            (*campos.values(), guild_id),
        )
        await self.bot.db.commit()

    async def categoria_add_db(self, guild_id: int, valor: str, label: str, emoji: str | None) -> tuple[bool, str]:
        async with self.bot.db.execute(
            "SELECT COALESCE(MAX(posicao), -1) + 1 FROM categorias WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            (posicao,) = await cursor.fetchone()
        try:
            await self.bot.db.execute(
                "INSERT INTO categorias (guild_id, valor, label, emoji, posicao) VALUES (?, ?, ?, ?, ?)",
                (guild_id, valor, label, emoji, posicao),
            )
            await self.bot.db.commit()
        except sqlite3.IntegrityError:
            return False, f"Ja existe uma categoria com o valor `{valor}`."
        return True, f"Categoria `{valor}` adicionada. Roda /ticket-painel de novo pra republicar com as mudancas."

    async def categoria_remover_db(self, guild_id: int, valor: str) -> tuple[bool, str]:
        async with self.bot.db.execute(
            "SELECT COUNT(*) FROM categorias WHERE guild_id = ? AND valor = ?", (guild_id, valor)
        ) as cursor:
            (encontrada,) = await cursor.fetchone()
        if not encontrada:
            return False, "Nao achei essa categoria."

        async with self.bot.db.execute(
            "SELECT COUNT(*) FROM categorias WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            (total,) = await cursor.fetchone()
        if total <= 1:
            return False, "Essa e a unica categoria cadastrada, o painel ficaria sem opcao nenhuma."

        await self.bot.db.execute("DELETE FROM categorias WHERE guild_id = ? AND valor = ?", (guild_id, valor))
        await self.bot.db.commit()
        return True, f"Categoria `{valor}` removida. Roda /ticket-painel de novo pra republicar com as mudancas."

    async def publicar_painel(self, guild_id: int, channel) -> tuple[bool, str]:
        config = await self._get_painel_config(guild_id)
        categorias = await self._get_categorias(guild_id)
        if not categorias:
            return False, "Cadastra pelo menos uma categoria antes de publicar."

        view = PainelView(config["titulo"], config["descricao"], config["cor"], categorias)
        try:
            await channel.send(view=view)
        except discord.HTTPException:
            return False, "Deu erro ao publicar o painel — confere se algum emoji configurado e invalido."
        return True, "Painel publicado!"

    async def _e_staff(self, membro: discord.Member) -> bool:
        if membro.guild_permissions.manage_guild:
            return True
        config = await self._get_painel_config(membro.guild.id)
        staff_role_id = config["staff_role_id"]
        if not staff_role_id:
            return False
        return any(role.id == staff_role_id for role in membro.roles)

    @app_commands.command(name="ticket-painel", description="Publica o painel de abertura de tickets")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def ticket_painel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        _, msg = await self.publicar_painel(interaction.guild_id, interaction.channel)
        await interaction.followup.send(msg, ephemeral=True)

    @ticket_config.command(name="dashboard", description="Abre o painel visual de configuracao dos tickets")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def ticket_config_dashboard(self, interaction: discord.Interaction):
        config = await self._get_painel_config(interaction.guild_id)
        categorias = await self._get_categorias(interaction.guild_id)
        await interaction.response.send_message(view=DashboardView(self, config, categorias), ephemeral=True)

    @ticket_config.command(name="editar", description="Edita titulo, descricao, cor, textos e limite do painel")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def ticket_config_editar(
        self,
        interaction: discord.Interaction,
        titulo: str = None,
        descricao: str = None,
        cor: str = None,
        fechar_label: str = None,
        fechar_emoji: str = None,
        assumir_label: str = None,
        assumir_emoji: str = None,
        boas_vindas: str = None,
        limite_por_usuario: app_commands.Range[int, 0, 999] = None,
    ):
        campos = {}
        if titulo:
            campos["titulo"] = titulo
        if descricao:
            campos["descricao"] = descricao
        if cor:
            try:
                campos["cor"] = int(cor.lstrip("#"), 16)
            except ValueError:
                await interaction.response.send_message("Cor invalida, manda um hex tipo #5865F2.", ephemeral=True)
                return
        if fechar_label:
            campos["fechar_label"] = fechar_label
        if fechar_emoji:
            campos["fechar_emoji"] = fechar_emoji
        if assumir_label:
            campos["assumir_label"] = assumir_label
        if assumir_emoji:
            campos["assumir_emoji"] = assumir_emoji
        if boas_vindas:
            campos["boas_vindas"] = boas_vindas
        if limite_por_usuario is not None:
            campos["limite_por_usuario"] = limite_por_usuario

        if not campos:
            await interaction.response.send_message("Nada pra atualizar.", ephemeral=True)
            return

        await self.atualizar_config(interaction.guild_id, campos)
        await interaction.response.send_message(
            "Painel atualizado. Roda /ticket-painel de novo pra republicar com as mudancas.", ephemeral=True
        )

    @ticket_config.command(name="categoria-add", description="Adiciona uma categoria no painel")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def categoria_add(self, interaction: discord.Interaction, valor: str, label: str, emoji: str = None):
        _, msg = await self.categoria_add_db(interaction.guild_id, valor, label, emoji)
        await interaction.response.send_message(msg, ephemeral=True)

    @ticket_config.command(name="categoria-remover", description="Remove uma categoria do painel")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def categoria_remover(self, interaction: discord.Interaction, valor: str):
        _, msg = await self.categoria_remover_db(interaction.guild_id, valor)
        await interaction.response.send_message(msg, ephemeral=True)

    @categoria_remover.autocomplete("valor")
    async def categoria_remover_autocomplete(self, interaction: discord.Interaction, current: str):
        categorias = await self._get_categorias(interaction.guild_id)
        current = current.lower()
        return [
            app_commands.Choice(name=f"{label} ({valor})", value=valor)
            for valor, label, _ in categorias
            if current in valor.lower() or current in label.lower()
        ][:25]

    @ticket_config.command(name="categoria-listar", description="Lista as categorias do painel")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def categoria_listar(self, interaction: discord.Interaction):
        categorias = await self._get_categorias(interaction.guild_id)
        if not categorias:
            await interaction.response.send_message("Nenhuma categoria cadastrada.", ephemeral=True)
            return
        linhas = [f"`{valor}` — {label}" + (f" {emoji}" if emoji else "") for valor, label, emoji in categorias]
        await interaction.response.send_message("\n".join(linhas), ephemeral=True)

    async def criar_ticket(self, interaction: discord.Interaction, categoria: str, assunto: str, descricao: str):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        config = await self._get_painel_config(guild.id)

        if config["limite_por_usuario"] > 0:
            async with self.bot.db.execute(
                "SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND user_id = ? AND status = 'aberto'",
                (guild.id, interaction.user.id),
            ) as cursor:
                (abertos,) = await cursor.fetchone()
            if abertos >= config["limite_por_usuario"]:
                await interaction.followup.send(
                    f"Voce ja tem {abertos} ticket(s) aberto(s), o limite e {config['limite_por_usuario']}.",
                    ephemeral=True,
                )
                return

        async with self.bot.db.execute(
            "SELECT label FROM categorias WHERE guild_id = ? AND valor = ?", (guild.id, categoria)
        ) as cursor:
            row = await cursor.fetchone()
        categoria_label = row["label"] if row else categoria

        categoria_canal = guild.get_channel(config["categoria_tickets_id"]) if config["categoria_tickets_id"] else None
        staff_role = guild.get_role(config["staff_role_id"]) if config["staff_role_id"] else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if staff_role is not None:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        criado_em = discord.utils.utcnow().isoformat()
        cursor = await self.bot.db.execute(
            "INSERT INTO tickets (guild_id, user_id, categoria, assunto, descricao, criado_em) VALUES (?, ?, ?, ?, ?, ?)",
            (guild.id, interaction.user.id, categoria, assunto, descricao, criado_em),
        )
        await self.bot.db.commit()
        ticket_id = cursor.lastrowid

        try:
            canal = await guild.create_text_channel(
                name=f"ticket-{ticket_id:04d}",
                category=categoria_canal,
                overwrites=overwrites,
                reason=f"ticket aberto por {interaction.user}",
            )
        except discord.HTTPException:
            await self.bot.db.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
            await self.bot.db.commit()
            await interaction.followup.send(
                "Deu erro ao criar o canal do ticket (permissao do bot ou categoria cheia). Chama o staff.",
                ephemeral=True,
            )
            return

        await self.bot.db.execute("UPDATE tickets SET channel_id = ? WHERE id = ?", (canal.id, ticket_id))
        await self.bot.db.commit()

        boas_vindas = config["boas_vindas"].replace("{mention}", interaction.user.mention)

        container = discord.ui.Container(
            discord.ui.TextDisplay(boas_vindas),
            discord.ui.Section(
                f"## Ticket #{ticket_id:04d}",
                f"Categoria: {categoria_label}\nAssunto: {assunto}",
                accessory=discord.ui.Thumbnail(interaction.user.display_avatar.url),
            ),
            discord.ui.TextDisplay(descricao),
            discord.ui.Separator(),
            AcoesRow(
                config["assumir_label"],
                config["assumir_emoji"],
                config["fechar_label"],
                config["fechar_emoji"],
            ),
            accent_color=discord.Color(config["cor"]),
        )
        view = discord.ui.LayoutView(timeout=None)
        view.add_item(container)
        try:
            await canal.send(view=view)
        except discord.HTTPException:
            await self.bot.db.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
            await self.bot.db.commit()
            await canal.delete(reason="falha ao montar a mensagem do ticket")
            await interaction.followup.send(
                "Deu erro ao montar o ticket, provavelmente um emoji invalido configurado no painel. Chama o staff.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(f"Ticket criado: {canal.mention}", ephemeral=True)

    async def gerar_transcricao(self, canal: discord.TextChannel) -> str:
        linhas = []
        async for msg in canal.history(limit=None, oldest_first=True):
            hora = msg.created_at.strftime("%d/%m/%Y %H:%M:%S")
            conteudo = msg.content or "[sem texto]"
            linhas.append(f"[{hora}] {msg.author}: {conteudo}")
            for anexo in msg.attachments:
                linhas.append(f"  anexo: {anexo.url}")
        return "\n".join(linhas)

    async def assumir_ticket(self, interaction: discord.Interaction):
        if not await self._e_staff(interaction.user):
            await interaction.response.send_message("So a staff pode assumir ticket.", ephemeral=True)
            return

        canal = interaction.channel
        async with self.bot.db.execute("SELECT id, status FROM tickets WHERE channel_id = ?", (canal.id,)) as cursor:
            row = await cursor.fetchone()
        if row is None or row["status"] == "fechado":
            await interaction.response.send_message("Este canal nao e um ticket ativo.", ephemeral=True)
            return

        cursor = await self.bot.db.execute(
            "UPDATE tickets SET assumido_por = ? WHERE id = ? AND assumido_por IS NULL AND status != 'fechado'",
            (interaction.user.id, row["id"]),
        )
        await self.bot.db.commit()

        if cursor.rowcount == 0:
            async with self.bot.db.execute(
                "SELECT status, assumido_por FROM tickets WHERE id = ?", (row["id"],)
            ) as cursor:
                atual = await cursor.fetchone()
            if atual["status"] == "fechado":
                await interaction.response.send_message("Este ticket acabou de ser fechado.", ephemeral=True)
            else:
                await interaction.response.send_message(
                    f"Esse ticket ja foi assumido por <@{atual['assumido_por']}>.", ephemeral=True
                )
            return

        await interaction.response.send_message(f"{interaction.user.mention} assumiu esse ticket.")

    async def fechar_ticket(self, interaction: discord.Interaction):
        canal = interaction.channel
        async with self.bot.db.execute("SELECT id FROM tickets WHERE channel_id = ?", (canal.id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            await interaction.response.send_message("Este canal nao e um ticket ativo.", ephemeral=True)
            return

        fechado_em = discord.utils.utcnow().isoformat()
        cursor = await self.bot.db.execute(
            "UPDATE tickets SET status = 'fechado', fechado_em = ? WHERE id = ? AND status != 'fechado'",
            (fechado_em, row["id"]),
        )
        await self.bot.db.commit()
        if cursor.rowcount == 0:
            await interaction.response.send_message("Este canal nao e um ticket ativo.", ephemeral=True)
            return

        await interaction.response.defer()

        texto = await self.gerar_transcricao(canal)
        cfg_transcricao = self.bot.config.get("transcricoes", {})
        pasta = Path(cfg_transcricao.get("caminho", "data/transcricoes"))
        if cfg_transcricao.get("criar_pasta", True):
            await asyncio.to_thread(pasta.mkdir, parents=True, exist_ok=True)
        elif not pasta.is_dir():
            raise FileNotFoundError(f"pasta {pasta} nao existe")

        arquivo_path = pasta / f"ticket-{row['id']:04d}.txt"
        await asyncio.to_thread(arquivo_path.write_text, texto, encoding="utf-8")

        await self.bot.db.execute("UPDATE tickets SET transcricao = ? WHERE id = ?", (str(arquivo_path), row["id"]))
        await self.bot.db.commit()

        await interaction.followup.send(
            "Ticket fechado. Transcricao em anexo. O canal sera removido em instantes.",
            file=discord.File(arquivo_path, filename=arquivo_path.name),
        )

        config = await self._get_painel_config(interaction.guild_id)
        canal_log = interaction.guild.get_channel(config["log_channel_id"]) if config["log_channel_id"] else None
        if canal_log is not None:
            await canal_log.send(
                content=f"Transcricao do ticket #{row['id']:04d}",
                file=discord.File(arquivo_path, filename=arquivo_path.name),
            )

        await asyncio.sleep(5)
        try:
            await canal.delete(reason="ticket fechado")
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
