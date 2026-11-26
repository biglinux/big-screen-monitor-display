# 04 — Conexão pela rede (Wi-Fi / Ethernet)

## Ligar

Meus Displays › Celulares e tablets Android › **Conectar pela rede** (desligado por padrão) e
**Aplicar**. O serviço passa a escutar TCP **7717** (TLS) e UDP **7718** (descoberta) em todas as
interfaces. A unidade systemd só aceita endereços de loopback, privados (10/8, 172.16/12, 192.168/16),
link-local (169.254/16) e da faixa das VPNs Tailscale/Headscale/NetBird (100.64/10, que não é roteada
na Internet): mesmo com a porta exposta, nada da Internet pública chega ao serviço.
Porta configurável (`android_port`). Desligado e com USB ligado, escuta só em `127.0.0.1` (adb).

O computador no cabo e o celular no Wi-Fi funcionam, desde que estejam na mesma rede IP.

## Acesso remoto (Tailscale)

Para usar o display longe de casa, pelos dados móveis ou outro Wi-Fi:

1. Instale o [Tailscale](https://tailscale.com) no computador e no celular, na mesma conta (tailnet).
2. No computador, "Conectar pela rede" ligado e aplicado (a janela mostra em "Estado" o endereço
   `100.x.y.z (tailscale0)` junto com o da rede de casa).
3. Pareie em casa normalmente (QR Code ou código). A partir daí o app já sabe os dois endereços:
   o QR Code leva o do Tailscale, e a cada conexão o computador informa ao app os endereços atuais
   (campo `addresses` do `WELCOME`). Fora de casa, com o Tailscale ligado no celular, basta abrir o app.
4. Já pareado antes desta versão? Conecte uma vez em casa (o app aprende o endereço da VPN) ou
   use **Adicionar pelo endereço** com o IP do Tailscale (`100.x.y.z`) ou o nome MagicDNS do computador.

Como funciona:

* O serviço anuncia, nesta ordem: o endereço da rede da rota padrão (casa), os da faixa 100.64/10
  (Tailscale), as demais redes locais e as outras VPNs (ZeroTier, WireGuard). Bridges de contêineres
  e VMs (`docker`, `virbr`, `podman`…) e endereços públicos nunca são anunciados.
* O app tenta **todos os endereços ao mesmo tempo**; os da VPN começam 300 ms depois, para que em
  casa a rede local direta vença. Fica a primeira conexão que responder (até 8 s para o primeiro
  pacote do Tailscale, que pode passar por um relay DERP).
* A segurança não muda: TLS com certificado fixado e token do pareamento, iguais aos do Wi-Fi.
  Quem não está pareado não passa do handshake, mesmo dentro da tailnet.
* O app reconecta assim que uma rede — inclusive a VPN — fica disponível, e mostra o transporte
  **VPN (Tailscale)** na lista e no diagnóstico; a janela do computador mostra **VPN**.
* Pelos dados móveis, prefira **Qualidade › Economia** se o plano for limitado.

Firewall: o Tailscale no Linux já aceita o que chega por `tailscale0` (cadeia `ts-input`). Se o
firewall do computador filtrar mesmo assim (por exemplo regras do UFW só para `192.168.0.0/24`):

```bash
sudo ufw allow in on tailscale0 to any port 7717 proto tcp
sudo ufw allow in on tailscale0 to any port 7718 proto udp
```

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
UDP 7718 no firewall do PC (para o Tailscale, veja [Acesso remoto](#acesso-remoto-tailscale)) (`firewall-cmd --add-port=7717/tcp --add-port=7718/udp`, ou `ufw allow
7717/tcp` e `ufw allow 7718/udp`); conferir que o celular não está em rede de visitantes isolada.
A janela mostra em "Estado" os endereços em que o serviço está esperando.
