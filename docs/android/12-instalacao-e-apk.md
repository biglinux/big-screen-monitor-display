# 12 — Instalação e compilação do APK

## No computador

Pacote (BigLinux/Arch) ou `install-system.sh`: nada a mais a fazer além de atualizar. Dependência
nova `openssl` (já presente em qualquer sistema); opcional `python-qrcode` para o QR Code (o caminho
manual funciona sem ele; o instalador o lista entre os opcionais). Depois:

1. Big Screen Monitor Display › Meus Displays › Celulares e tablets Android › **Conectar pela rede** › Aplicar.
2. **Adicionar Android…** e ler o QR Code com a câmera do celular (o app precisa estar instalado).

Firewall: liberar TCP 7717 e UDP 7718 se houver (ver 04).

## No celular

Baixar o APK da versão mais nova, direto pelo navegador do celular (Android 5.0+):

**<https://github.com/ruscher/big-screen-monitor-display/releases/latest/download/big-screen-monitor-display.apk>**

O endereço não muda entre versões: cada release do GitHub traz o arquivo com esse nome, uma cópia
com a versão no nome (`big-screen-monitor-display-5.5.2.apk`) e o `SHA256SUMS`. A janela
*Adicionar Android…* mostra o mesmo endereço. Fora de uma loja, o Android pede "Permitir fontes
desconhecidas" para o aplicativo usado para abrir o arquivo.

A partir da 5.5.2 o APK publicado é assinado com a **chave oficial** do projeto (segredos `BSMD_*`
do repositório; certificado SHA-256 `DE:6C:5E:64:52:18:5C:BA:9C:8B:60:AA:75:B3:70:8A:D3:D5:A2:DB:84:AC:E7:BC:60:B9:DC:DC:87:78:CF:73`),
pacote `br.com.biglinux.bigscreen`. As atualizações seguintes instalam por cima, mantendo o
pareamento.

Até a 5.5.1 o APK publicado era a compilação de depuração (pacote `br.com.biglinux.bigscreen.debug`),
e cada build do CI gerava uma chave de depuração nova: de uma versão para a outra o Android recusava
a atualização ("conflito com pacote existente"). Quem tem esse app instala a 5.5.2 (ela aparece ao
lado, com o mesmo nome), pareia uma vez e desinstala o antigo.

## Compilar o APK

Requisitos: JDK 17+ (testado no CI com Temurin 21), Android SDK (plataforma 36), Gradle 9.7+.

```sh
gradle -p android testDebugUnitTest      # protocolo contra tests/data/bsdp-vectors.json
gradle -p android lintDebug
gradle -p android assembleDebug          # android/app/build/outputs/apk/debug/app-debug.apk
```

O repositório não inclui o `gradle-wrapper.jar`; com o Android Studio, "Open" na pasta `android/`
também funciona.

### Release

`gradle -p android assembleRelease` minifica (R8). A assinatura de produção só existe quando
configurada fora do repositório: variáveis `BSMD_KEYSTORE`, `BSMD_KEYSTORE_PASSWORD`,
`BSMD_KEY_ALIAS`, `BSMD_KEY_PASSWORD` ou um `android/keystore.properties` (ignorado pelo git). Sem
isso o release sai **sem assinatura** e não deve ser publicado como versão oficial. A chave oficial
(PKCS12, alias `bsmd`, válida até 2056) fica fora do repositório, com o mantenedor, e nos segredos do
GitHub; perdê-la impede atualizar o app por cima (os aparelhos teriam de desinstalar e parear de novo).

### GitHub Actions

`.github/workflows/android.yml` roda JUnit, lint, `assembleDebug` e `assembleRelease` a cada mudança
em `android/` ou nos vetores do protocolo, e publica os APKs e relatórios como artefato. Numa tag
`v*` (por exemplo `v5.5.2`, igual ao `versionName`), o mesmo workflow cria a release e anexa
`big-screen-monitor-display.apk`, a cópia com versão e o `SHA256SUMS`: o APK assinado quando os
segredos existem, senão o de depuração — nunca um APK sem assinatura. Para
assinar no CI, cadastrar os segredos `BSMD_KEYSTORE_BASE64` (keystore em base64),
`BSMD_KEYSTORE_PASSWORD`, `BSMD_KEY_ALIAS` e `BSMD_KEY_PASSWORD`.

### Ícones

`tools/android-icons.py` gera os ícones do lançador (comuns e adaptativos) e o logo do app a partir
do SVG oficial (`rsvg-convert` + Pillow).
