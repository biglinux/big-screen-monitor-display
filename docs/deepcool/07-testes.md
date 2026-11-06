# 07 — Testes

## Classes de validação

| Classe | Significado |
| --- | --- |
| A | Validado neste projeto em hardware real |
| **B** | Implementado a partir de protocolos documentados e conferido com dados de referência; hardware real pendente |
| C | Protocolo conhecido, implementação em andamento |
| D | Em investigação |
| E | Não suportado |

**Todas as famílias DeepCool estão na classe B.** Nenhum cooler foi
conectado durante o desenvolvimento; nenhum modelo é anunciado como
validado fisicamente.

## Testes automatizados

`tests/test_deepcool.py` — 44 testes, sem hardware:

| Área | O que é verificado |
| --- | --- |
| Pacotes | AK (°C, °F, uso, alarme, limites), SE sem report id, AG (2 dígitos, alarme no byte 5), AK PRO byte a byte, AK400 PRO e LD sem frequência, limites de u16/uso, init do LD |
| MYSTIQUE | Checksum contra captura real de hardware, moldura AA 2E/"HIDC", pacote de atualização, **ausência de comandos de upload** |
| Detecção | Classificação só por VID/PID, descoberta de nós hidraw em um sysfs falso, IDs dos perfis nas configurações |
| Telemetria | Potência por delta RAPL, *wraparound*, reinício do zenergy, valores absurdos, permissão negada (sem 0 W), frequência máxima, preferência Tdie > Tctl |
| Métricas | Valores nunca inventados, alternância automática sem métricas ausentes, presets, adaptador de temas, matriz completa tema × família, campos ausentes e °F em layout fixo, alarme e Guardião |
| Driver HID | Fluxo completo com hidraw falso, recusa de identidade errada, permissão, `flock` (duas cópias não controlam o mesmo cooler), mapeamento de erros para recuperação |
| Driver MYSTIQUE | Init, rotação e atualização com pyusb falso; erros |
| Conflitos | Processos e units conhecidos |
| Runtime | Cooler ao lado de um painel raster (sessões independentes); recuperação após `ENODEV` repetindo o init |
| udev | Lista de PIDs idêntica à dos modelos suportados; nenhum `0666`; RAPL só 0440 para o grupo |
| Prévia / GUI | Todas as famílias desenham; campos ausentes destacados; origem da prévia (ao vivo × DEMO); dispositivos não suportados; permissões do nó |

`tests/test_gui.py::test_deepcool_cooler_pages` — sessão GTK real com um
status falso (um painel simulado + um AK620 DIGITAL PRO): cartão, miniatura,
página de detalhe, selo "Ao vivo", valores, motivo da potência ausente,
gravação de `dc_preset`, diagnóstico em JSON, painel ao lado continua raster,
prévia do painel inicial desenhando a face do cooler.

Suíte completa: **1289 testes passando** (eram 1245 antes da integração).

Execução:

```
python -m pytest -q tests/test_deepcool.py
python -m pytest -q tests            # suíte inteira (GUI precisa de sessão gráfica)
```

## Testes físicos pendentes (por família)

Para promover uma família à classe A, com o pacote instalado e o serviço
ativo:

1. **Detecção** — `lsusb -d 3633:` mostra o PID esperado; o cartão aparece
   com o modelo correto; o diagnóstico mostra o `hidraw` com grupo
   `big-screen-monitor` e modo `crw-rw----`.
2. **Valores** — comparar o visor com `sensors` e `cat /proc/cpuinfo` por
   2 minutos (temperatura ±1 °C; uso coerente com `top`).
3. **Campo único (AK/AG/LS)** — Essencial alterna a cada 5 s; Mínimo fixa a
   temperatura; °F aparece com o rótulo °F (AK/LS).
4. **Barra (AK/LS)** — sob `stress -c N`, a barra sobe até 10 segmentos.
5. **Alarme por software** — limite em 60 °C sob carga: luz acende; volta ao
   apagar.
6. **SE** — um AK400/AK620 SE mostra os mesmos valores (sem deslocamento de
   bytes).
7. **AK PRO / LD** — potência, temperatura, uso (e frequência no AK PRO) nos
   campos certos; potência em W coerente com `turbostat`/RAPL; LD com e sem
   zeros à esquerda.
8. **MYSTIQUE** — entra em Machine Info; rotações 0/90/180/270; valores de
   GPU e RAM; reiniciar o serviço não deixa a tela presa.
9. **Recuperação** — desconectar e reconectar o cabo: volta em segundos sem
   reiniciar o serviço.
10. **Conflito** — com `deepcool-digital-linux` em execução, o diagnóstico o
    lista e o serviço informa "ocupado" em vez de intercalar pacotes.
11. **Multi-dispositivo** — cooler + painel LCD ao mesmo tempo, cada um com
    seu tema.
12. **Suspensão** — suspender e retomar: o cooler volta a ser atualizado.
