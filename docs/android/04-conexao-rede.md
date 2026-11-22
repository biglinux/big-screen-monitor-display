# 04 — Conexão pela rede (Wi-Fi / Ethernet)

## Ligar

Meus Displays › Celulares e tablets Android › **Conectar pela rede** (desligado por padrão) e
**Aplicar**. O serviço passa a escutar TCP **7717** (TLS) e UDP **7718** (descoberta) em todas as
interfaces. A unidade systemd só aceita endereços de loopback, privados (10/8, 172.16/12, 192.168/16)
e link-local (169.254/16): mesmo com a porta exposta, nada de fora da rede local chega ao serviço.
Porta configurável (`android_port`). Desligado e com USB ligado, escuta só em `127.0.0.1` (adb).

O computador no cabo e o celular no Wi-Fi funcionam, desde que estejam na mesma rede IP.

## Descoberta

O app envia `BSMD?1<nonce>` por broadcast (255.255.255.255 e o broadcast de cada interface) e
diretamente aos endereços dos computadores já conhecidos, duas vezes em 1,5 s. Cada computador
responde `BSMD!1{json}` com nome, id, porta, impressão digital do certificado e se há pareamento
aberto. **Sem mDNS**: o `avahi-daemon` nem sempre está ativo (inclusive na máquina de
desenvolvimento) e a resposta UDP não depende dele. A resposta não contém segredos e é limitada a
20/s. A impressão digital da descoberta **não** é usada para confiar: só QR Code ou código conferido.

Quando a descoberta falha (redes de visitantes isolam clientes, firewalls): **Adicionar pelo
endereço** (`192.168.1.20` ou `192.168.1.20:7717`). A janela mostra o endereço e a impressão digital.

## Pareamento

* **QR Code** (Adicionar Android…): `bsmd://pair?v=1&id&n&fp&p&a&t&s` — endereços, porta,
  impressão digital do certificado e um segredo de 144 bits de **uso único**, válido 5 min,
  renovado após cada pareamento. A câmera do sistema abre o link no app. O segredo é gerado pela
  janela e vai ao serviço só pelo spool root (`bsm-helper display-command`), nunca pelo status.
* **Confirmação**: escolher o computador na lista; os dois lados mostram o mesmo código de 6 dígitos
  (derivado do certificado visto pelo app e dos dois nonces); a pessoa permite na janela. Um
  intermediário com outro certificado produz códigos diferentes, e o app aborta sozinho.

## Reconexão

* Perda de rede, queda do serviço, suspensão do PC: o app tenta com espera crescente (1, 2, 4, 8,
  15, 30 s) e imediatamente quando o Android anuncia uma rede nova; mostra "Reconectando… (tentativa N)"
  sobre fundo preto — **o último quadro não fica na tela como se fosse atual**.
* Computadores conhecidos guardam até 6 endereços; o app tenta cada um.
* Certificado diferente do fixado: não conecta ("A identidade do computador mudou"); só esquecer e
  parear de novo resolve (reinstalação do PC).
* Lado do PC: a sessão do display espera o celular voltar (`DISCONNECTED`/`RETRYING`) e é removida
  depois de 45 s sem ele; as configurações do display continuam salvas.

## Diagnóstico de firewall

Se nenhum computador responde: conferir "Conectar pela rede" ligado e aplicado; liberar TCP 7717 e
UDP 7718 no firewall do PC (`firewall-cmd --add-port=7717/tcp --add-port=7718/udp`, ou `ufw allow
7717/tcp` e `ufw allow 7718/udp`); conferir que o celular não está em rede de visitantes isolada.
A janela mostra em "Estado" os endereços em que o serviço está esperando.
