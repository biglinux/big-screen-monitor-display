# Recuperação e solução de problemas

| Sintoma | Causa | O que fazer |
|---|---|---|
| Tocar em Navegação não abre nada | executável novo copiado sem reset; ou binário com função ausente no coredll | reset no FOSTON; usar o `bsmd-ce.exe` do pacote |
| Tela "Aguardando a porta USB serial" | cabo desconectado, ou troca de função recusada | conectar o cabo; ver as linhas verdes de diagnóstico |
| "Porta COMx ocupada" | ActiveSync (`repllog.exe`) segurou a porta | o cliente encerra `repllog.exe` e tenta de novo |
| Serviço: "the bsmd-ce client is not running" | cliente fechado no aparelho | abrir pela Navegação |
| Serviço: "client … is too old" | cliente 1.0.x (sem controle de fluxo) | instalar o cliente do pacote |
| `/dev/ttyUSB0` sem permissão | regra udev ausente | instalar o pacote ou a regra de desenvolvimento |
| "frame damaged on the link … resynchronising" no log | perda de bytes no driver serial do WinCE | nada: o quadro é refeito; se for frequente, perfil de desempenho "economia" |
| Volume não aparece no PC | cliente aberto (modo serial) | Sair no aparelho |

## Mecanismos automáticos

* **Cliente**: reabre a porta após falha; descarta mensagem parcial parada há 1 s
  (NAK motivo 6); mantém o aparelho acordado (`SystemIdleTimerReset` +
  requisito de energia na luz de fundo); executa da RAM (`\Temp`) para não
  depender do armazenamento.
* **Driver**: CRC/timeout no quadro → novo HELLO + quadro completo (1 tentativa);
  persistindo, entrega o erro ao runtime.
* **Runtime** (já existente): máquina de estados de link, backoff exponencial
  1–30 s, `probe` (PING) após 15 s parado, sessão por display — falha do FOSTON
  não para os demais (coberto por teste).

## Restaurar o estado original do aparelho

1. Configurações → Caminho da navegação → apontar de novo para o navegador original.
2. Apagar a pasta `BigScreen` do volume (opcional).
3. Os arquivos originais estão em `foston-monitor/backup/2026-11-18-volume/` com SHA-256.
