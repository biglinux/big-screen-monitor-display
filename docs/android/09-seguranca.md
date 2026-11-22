# 09 — Segurança e privacidade

O display mostra processos, endereços e hardware do computador; o celular manda toques e comandos.

| Ameaça | Proteção |
|---|---|
| Qualquer aparelho da rede pede a tela | só aparelhos pareados (token de 256 bits por aparelho, desafio-resposta HMAC-SHA256 com nonces dos dois lados); pareamento exige o QR Code mostrado no computador ou a aprovação na janela |
| Escuta na rede | TLS 1.2+ (certificado P-256 do computador, gerado com `openssl` no estado privado do serviço) |
| Intermediário (MITM) | o app fixa a impressão digital do certificado (do QR, ou da confirmação por código que cobre o certificado visto pelo app); certificado diferente → não conecta |
| Força bruta / abuso | 5 falhas por endereço → bloqueio de 60 s; no máximo 8 handshakes simultâneos e 4 pedidos pendentes; handshake com prazo de 10 s; descoberta limitada a 20 respostas/s; comandos do app limitados a 20/s; mídia a 10/s |
| Mensagens malformadas | cabeçalho, versão, tipo por sentido e tamanho checados antes de ler o payload; JSON validado campo a campo (strings imprimíveis com limite, números em faixa, id do aparelho só hex e hífen) |
| Comandos remotos | lista explícita: menu, tema anterior/próximo, fechar, `set` só com chaves da lista `DEVICE_SETTABLE` validadas pelo esquema de configurações, mídia só `play_pause/next/previous/volume_up/volume_down/mute`. O celular não altera configurações globais nem fala com o polkit; nada é injetado no desktop |
| Segredo do QR vazando | 144 bits, uso único, 5 min; gerado pela janela e entregue ao serviço pelo spool root; nunca no status nem no log |
| Token no celular | Android Keystore (AES-GCM, chave não exportável) no Android 6+; no 5.x, armazenamento privado do app (limitação documentada); fora de backup e de cópia entre aparelhos |
| Token no computador | `paired.json` 0600 no `StateDirectory` (usuário dinâmico do serviço), nunca publicado |
| Serviço exposto à internet | rede **desligada por padrão**; com ela ligada, a unidade systemd ainda bloqueia endereços públicos |
| USB | o serviço só acessa celulares já em modo acessório (pedido pela sessão do usuário); o serial USB é guardado só como hash |
| Revogação | "Remover pareamento" apaga o token e derruba a conexão na hora (BYE `revoked`) |
| Identificadores sensíveis | o app usa um UUID aleatório por instalação (sem IMEI, serial, conta) |

Sem servidores externos, sem nuvem, sem internet: tudo acontece na rede local ou no cabo.
Permissões do app: só rede (ver 06). Logs não contêm tokens, segredos nem provas.
