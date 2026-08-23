# Bot de Ticket

Bot de ticket pro Discord, feito em discord.py 2.x com SQLite.

O usuário escolhe a categoria num select, preenche assunto e descrição num modal e o
bot abre um canal privado só pra ele e pra staff. Tem botão de assumir, pra staff
saber quem está cuidando, e botão de fechar, que gera a transcrição em txt, manda no
canal de log e apaga o canal.

Usei os components novos do Discord (Container, Section, Separator) em vez de embed,
então o painel fica com a cara nova mesmo. As ações de assumir e fechar rodam num
update atômico, então dois staffs clicando junto não bagunçam o estado do ticket.

Tem também um cog que transforma imagem postada no chat em emoji do servidor, com
limite por servidor e nome tratado.

## Rodando

```bash
pip install -r requirements.txt
cp .env.example .env
```

Põe o token do bot no `.env` e o ID do teu servidor no `config/config.yaml`:

```yaml
guild_id: 000000000000000000
```

Só o `guild_id` é obrigatório. Cargo de staff, categoria dos tickets e canal de log
dá pra deixar em 0 e configurar depois pelo `/ticket-config dashboard`, dentro do
Discord mesmo, que é bem mais prático que ficar catando ID no yaml.

```bash
python main.py
```

## Comandos

| Comando | O que faz |
|---|---|
| `/ticket-painel` | Publica o painel no canal atual |
| `/ticket-config dashboard` | Configura tudo por botão (textos, cores, limite, cargos, canais) |
| `/ticket-config editar` | Mesma coisa, mas por opção do slash |
| `/ticket-config categoria-add` | Adiciona categoria |
| `/ticket-config categoria-remover` | Remove categoria |
| `/ticket-config categoria-listar` | Lista as categorias |

Todos pedem permissão de gerenciar servidor.

## Permissões que o bot precisa

Gerenciar canais e cargos, pra montar as permissões do canal do ticket, mais ler
histórico e anexar arquivo. Gerenciar emojis só se você quiser o cog de emoji.

## Licença

MIT. Pode usar, mexer e distribuir à vontade, é só manter os créditos e o arquivo
[LICENSE](LICENSE) junto.
