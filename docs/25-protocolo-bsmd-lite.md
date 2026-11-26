# 25 — Protocolo BSMD-lite (clientes caseiros)

Telemetria do computador para displays feitos em casa (ESP32 ou Arduino com
tela, Raspberry Pi, aparelhos antigos), em **uma linha de texto por amostra**.
Implementação: `bsmd/lite.py`. Bridge: `device-clients/lite/bsmd_lite_bridge.py`.
Cliente de referência: `device-clients/lite/lite_client.py`.

## Por que existe

O ZireMon (Palm, PR #19) trouxe a sua própria leitura da telemetria e errou as
chaves da GPU (sempre 0 %). Cada cliente novo reimplementando a leitura repetiria
o erro. Agora `bsmd.lite.metrics()` é o único lugar que lê o *snapshot*, e a bridge
do Palm também usa essa função.

## Formato

```
BSMD1|cpu=13|cpu_t=61|cpu_mhz=4120|gpu=77|gpu_t=66|gpu_mhz=2400|ram=33|ram_used=15.5|ram_total=46.4|disk=63|rx=1.2|tx=0.0|host=estacao|media=Banda - Música\n
```

| Regra | Por quê |
| --- | --- |
| Começa com `BSMD1` (versão) | o cliente recusa uma versão que não conhece |
| `chave=valor` em qualquer ordem | chaves novas nunca quebram clientes antigos: quem não conhece, ignora |
| `-` = **não medido** | uma GPU sem relatório de uso ou um sensor ausente nunca vira 0 |
| texto sem `\|`, `=` nem controles; `host` ≤ 20 e `media` ≤ 48 bytes | o separador não aparece dentro de um valor |
| cp1252 (compatível com Latin-1), ≤ 255 bytes com o `\n`, campos nunca cortados ao meio | cabe num buffer fixo de microcontrolador e dá para processar no lugar |

### Campos da versão 1

| Chave | Unidade | Chave | Unidade |
| --- | --- | --- | --- |
| `cpu` | % | `ram` | % |
| `cpu_t` | °C | `ram_used`, `ram_total` | GB (1 casa) |
| `cpu_mhz` | MHz | `disk` | % (raiz) |
| `gpu` | % | `rx`, `tx` | Mbps (1 casa) |
| `gpu_t` | °C | `host` | texto |
| `gpu_mhz` | MHz | `media` | "Artista - Título" (`-` sem música) |

A GPU é a de mais VRAM (a dedicada), ou `--gpu N`. O serviço alterna a GPU ativa a
cada 3 s para os temas dele; um display que só escreve "GPU" misturaria as duas.

## Comandos do cliente

O cliente pode responder com uma linha por comando:

`CMD|PLAY_PAUSE` · `CMD|NEXT` · `CMD|PREV` · `CMD|VOL_UP` · `CMD|VOL_DOWN`

A lista é fechada (`bsmd.lite.COMMANDS`): qualquer outra coisa é ignorada e
nada vindo do cliente chega a um shell. O volume usa `pactl` ou `wpctl` (com
limite de 100 %).

## Transportes

| Modo | Comando | Segurança |
| --- | --- | --- |
| Serial (USB) | `bsmd_lite_bridge.py --serial /dev/ttyUSB0 --baud 115200` | só o aparelho no cabo |
| TCP | `bsmd_lite_bridge.py --tcp 7720` | **só loopback por padrão**; `--bind 0.0.0.0` expõe à rede, de propósito |
| Terminal | `bsmd_lite_bridge.py --stdout` | teste |

A bridge roda como o seu usuário (precisa da sessão para `playerctl`), não dentro
do serviço isolado. Isso é intencional: o serviço não abre portas novas por causa
de um cliente caseiro.

## Escrevendo um cliente

1. Leia até `\n` num buffer de 256 bytes.
2. Confira o prefixo `BSMD1|`.
3. Separe por `|` e cada parte por `=`.
4. Trate `-` como "sem valor": mostre "—" e não desenhe barra.

O `lite_client.py` faz isso em 15 linhas de Python sem dependências, como modelo
para portar para C. Os testes (`tests/test_lite.py`) cobrem o formato, o tamanho,
os textos maliciosos e uma sessão TCP completa entre a bridge e o cliente.

## Próximo passo

Um exemplo para ESP32 com tela TFT, validado num aparelho. Não foi incluído sem
hardware para testar; contribuições pelo formulário de ideia são bem-vindas.
