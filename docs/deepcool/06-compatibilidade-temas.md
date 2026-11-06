# 06 — Compatibilidade de temas (Theme Capability Adapter)

Um cooler numérico não desenha imagens. Em vez de recusar os temas, cada
tema é **representado** pelo preset que melhor traduz sua intenção. Com
"Apresentação: Seguir o tema" (padrão), trocar o tema de um cooler troca o
preset; escolher um preset explicitamente ignora o tema.

## Presets nativos

| Preset | AK / AG (temp, uso) | LS (temp, potência) | AK PRO / LD / MYSTIQUE |
| --- | --- | --- | --- |
| CPU Essencial | Alterna temp/uso a cada 5 s | Alterna temp/potência | Campos fixos |
| CPU Avançado | Alterna entre todos disponíveis | Alterna | Campos fixos |
| CPU Guardião | Temperatura fixa + alarme sempre armado | Temperatura + alarme | Campos fixos + alarme do firmware |
| CPU Desempenho | Uso | Potência | Campos fixos |
| CPU Mínimo | Temperatura | Temperatura | Campos fixos |
| CPU Personalizado | Campo escolhido em "Campo configurável" | idem | Campos fixos |

## Matriz tema × família

| Tema | Preset | AK / AG / LS | AK PRO / AK400 PRO / LD | MYSTIQUE |
| --- | --- | --- | --- | --- |
| Padrão | Essencial | Compatível com adaptação | Compatível com adaptação | Compatível com adaptação |
| GKrellM | Desempenho | Compatível com adaptação | Compatível com adaptação | Compatível com adaptação |
| Kojiro | Personalizado | Compatível com adaptação | Compatível com adaptação | Compatível com adaptação |
| Planeta | Essencial | Parcialmente compatível | Parcialmente compatível | Parcialmente compatível |
| Computador antigo | Essencial | Parcialmente compatível | Parcialmente compatível | Parcialmente compatível |
| Brother Away | Guardião | Não compatível | Não compatível | Não compatível |
| Big Media Player | Essencial | Não compatível | Não compatível | Não compatível |

"Não compatível" significa que o visual do tema não existe no cooler; o
cooler continua monitorando a CPU com o preset indicado — nunca fica parado
nem mostra valores falsos.

No MYSTIQUE, o firmware desenha a própria tela de informações; nenhum tema
pode ser enviado porque não existe transferência de imagem ao vivo comprovada
como segura (ver [03-protocolos](03-protocolos.md)).

Fonte única: `metrics.THEME_ADAPTER` e `metrics.compatibility()`; a interface
lê os mesmos dados, e `test_compatibility_matrix_covers_every_theme_and_family`
garante que todo tema registrado tem estado para toda família.
