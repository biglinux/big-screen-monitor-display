# 12 — Instalação e compilação do APK

## No computador

Pacote (BigLinux/Arch) ou `install-system.sh`: nada a mais a fazer além de atualizar. Dependência
nova `openssl` (já presente em qualquer sistema); opcional `python-qrcode` para o QR Code (o caminho
manual funciona sem ele; o instalador o lista entre os opcionais). Depois:

1. Big Screen Monitor Display › Meus Displays › Celulares e tablets Android › **Conectar pela rede** › Aplicar.
2. **Adicionar Android…** e ler o QR Code com a câmera do celular (o app precisa estar instalado).

Firewall: liberar TCP 7717 e UDP 7718 se houver (ver 04).

## No celular

Instalar o APK (Android 5.0+). Fora de uma loja, o Android pede "Permitir fontes desconhecidas"
para o aplicativo usado para abrir o arquivo.

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
isso o release sai **sem assinatura** e não deve ser publicado como versão oficial. Nenhuma chave ou
senha foi criada nesta entrega.

### GitHub Actions

`.github/workflows/android.yml` roda JUnit, lint, `assembleDebug` e `assembleRelease` a cada mudança
em `android/` ou nos vetores do protocolo, e publica os APKs e relatórios como artefato. Para
assinar no CI, cadastrar os segredos `BSMD_KEYSTORE_BASE64` (keystore em base64),
`BSMD_KEYSTORE_PASSWORD`, `BSMD_KEY_ALIAS` e `BSMD_KEY_PASSWORD`.

### Ícones

`tools/android-icons.py` gera os ícones do lançador (comuns e adaptativos) e o logo do app a partir
do SVG oficial (`rsvg-convert` + Pillow).
