# 05 — Interface

Linguagem visual AshyWall da v5.0: cartões na galeria "Meus Displays",
página de detalhe com prévia à esquerda e grupos de preferências.

## Galeria

Coolers aparecem na mesma galeria dos painéis, com ícone próprio e:

* **título** — nome dado pelo usuário ou modelo detectado (ex.: AK620 DIGITAL PRO);
* **legenda** — estado · tipo de visor · modo ativo
  (ex.: "Funcionando · Visor numérico · CPU Essencial (do tema Padrão)");
* **dica (tooltip)** — modelo, fabricante, tipo de visor, protocolo, métricas e
  compatibilidade com o tema;
* **miniatura** — desenho da face do cooler com os últimos valores enviados
  pelo serviço, ou valores de exemplo marcados **DEMO** quando o serviço não
  está controlando o cooler.

Dispositivos `3633` identificados mas sem protocolo implementado aparecem
em "Outros dispositivos DeepCool", com a explicação e o aviso "Nada é
enviado a ele".

## Página do cooler

| Grupo | Conteúdo |
| --- | --- |
| Prévia | Face do cooler (AK/LS: dígitos, rótulos °C/%/W, barra e luz de alarme; AG: dois dígitos; AK PRO/LD: campos fixos, ausentes em vermelho; MYSTIQUE: tela de informações). Selo **Ao vivo** ou **DEMO · valores de exemplo**. Legenda: "o cooler desenha seus próprios dígitos: nenhuma imagem é enviada a ele" |
| Este cooler | Nome, usar/não usar, modelo, fabricante, tipo de visor, protocolo, sobre o modelo, métricas, compatibilidade com o tema (selo) e a matriz de compatibilidade com cada tema |
| Exibição | Tema, apresentação (Seguir o tema + 6 presets), "Exibindo agora", campo configurável (só AK/AG/LS, ativo no preset Personalizado) ou lista de campos fixos |
| Informações da CPU | Unidade (quando o modelo aceita °F), fonte da frequência (AK PRO/MYSTIQUE), valores atuais |
| Alertas | Alarme por software e limite (AK/AG/LS); alarme do firmware como informação (AK PRO/LD/MYSTIQUE), nunca alterado |
| Desempenho | Intervalo de atualização; contagem de atualizações, tempo por pacote, recuperações |
| Diagnóstico | Estado, USB (IDs, porta, produto, hidraw, variante SE), permissões do nó (modo e grupo), sensores (fonte de temperatura e de potência), valores indisponíveis com motivo, outros programas DeepCool com a sugestão de comando, última atualização, validação. Botão para copiar o diagnóstico em JSON |
| Avançado | Rotação (MYSTIQUE), zeros à esquerda (LD), modelo/protocolo manual, reconectar |

## Painel inicial

Quando o display selecionado é um cooler, a prévia do painel inicial passa a
desenhar a face do cooler (o renderizador de temas não é usado) e a linha
"Resolução" mostra "Visor numérico" ou "Tela LCD (modo de informações)".

## Conflitos

A lista de outros programas é apenas informativa. O texto sugere, por
exemplo, `sudo systemctl disable --now deepcool-digital.service`, mas **nada
é parado ou desinstalado** pelo programa.

## Acessibilidade e tradução

Todos os textos passam por `gettext` (pt traduzido; demais idiomas pelo fluxo
de tradução do projeto). Linhas de propriedade usam `subtitle_selectable` para
copiar valores; o botão de cópia tem rótulo acessível.
