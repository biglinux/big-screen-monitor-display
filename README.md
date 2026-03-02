# Big Screen Monitor Display 3.0

<p align="center">
  <img src="usr/share/icons/hicolor/scalable/apps/big-screen-monitor-display.svg" width="128" alt="Big Screen Monitor Display"/>
</p>

<p align="center">
  <b>Dashboard de monitoramento de hardware livre para displays USB LCD AX206</b>
</p>

---

## 📜 A História por trás do Projeto

O **Big Screen Monitor Display** nasceu de um desejo pessoal e de um desafio técnico. **Rafael Ruscher** queria um mini display para compor seu gabinete com informações de hardware em tempo real. Ele encontrou uma telinha pequena e simples, mas ao recebê-la, percebeu um grande obstáculo: o dispositivo era projetado para funcionar exclusivamente no Windows e dependia de softwares proprietários como o AIDA64.

Como usuário fiel de Linux, Rafael não tinha intenção de migrar para o Windows apenas para usar o acessório. Sem encontrar soluções que realmente funcionassem para suas necessidades, e por ser um dispositivo de custo muito baixo, ele acabou deixando a tela guardada em uma gaveta por alguns anos.

Recentemente, ao organizar seu setup, ele reencontrou o mini display. Aquela vontade de vê-lo brilhando dentro do gabinete acendeu novamente. Desta vez, unindo seu conhecimento técnico com o apoio de Inteligência Artificial para acelerar o desenvolvimento, Rafael criou sua própria solução. O resultado é este projeto: uma ferramenta robusta, moderna e, acima de tudo, **Software Livre**. Agora, qualquer usuário Linux pode usar, modificar, distribuir e estudar como o monitor interage com o hardware.

> "Ele é excelente para quem, como eu, não sai do `htop` ou do `gkrellm` e quer um resumo visual sempre à mão." — *Rafael Ruscher*

---

## ✨ Funcionalidades Principais (v3.0)

Esta versão marca um salto qualitativo no monitoramento, trazendo recursos avançados inspirados em ferramentas clássicas do Linux:

- 🎨 **Temas Dinâmicos:** Inclui o novo modo **GKrellM**, com sub-estilos como *Urlicht (Neon Blue)*, *Classic (Fósforo Verde)* e *Cyber-Red*.
- 📊 **Gráfico de CPU Avançado:** Visualização em ondas que se movem da direita para a esquerda, com camadas sobrepostas diferenciando o uso de **Usuário** (User Space) e **Sistema** (Kernel Space).
- 🎮 **Suporte Multi-GPU:** Monitoramento completo de múltiplas placas de vídeo simultâneas (AMD, Intel, NVIDIA) com sensores de temperatura, memória, potência (PPT) e carga de Encode/Decode.
- 🔠 **Letreiro Marquee:** Nomes grandes de GPUs ou do Kernel agora passam como um letreiro deslizante (bounce effect) para garantir visibilidade total.
- 📱 **Modo Retrato Inteligente:** Ajuste automático para telas verticais com layout inteligente de 2 colunas.
- ⚙️ **Interface de Configuração Adwaita:** Janela moderna e acessível (GTK4/Adwaita) para personalizar todas as opções, brilho e módulos visíveis.
- 🌐 **Rede e Sensores:** Tráfego RX/TX em tempo real, temperaturas de cores dinâmicas e monitoramento de conexões.

---

## 🔧 Instalação

### Arch Linux / BigLinux
A forma recomendada é através do PKGBUILD incluso:

```bash
cd pkgbuild
makepkg -si
```

### Estrutura de Diretórios
O projeto segue o padrão organizacional do **BigLinux Settings**:
- `usr/`: Binários, serviços de sistema, arquivos .desktop e a lógica em Python.
- `locale/`: Arquivos de tradução (PO/POT).
- `pkgbuild/`: Arquivos para empacotamento oficial.

---

## 📦 Dependências

- `python` >= 3.10
- `python-pillow` (Renderização de imagem)
- `python-psutil` (Coleta de estatísticas)
- `python-pyusb` (Comunicação USB low-level)
- `librsvg` (Suporte a ícones vetoriais)
- `lm_sensors` (Leitura de hardware)

---

## 📄 Licença

Este software é distribuído sob a licença **GPL-3.0**. O código é aberto para estudo, modificação e distribuição, fortalecendo a comunidade de software livre brasileira.

---

## 👤 Desenvolvedor

**Rafael Ruscher** (Equipe BigLinux)  
[GitHub do Projeto](https://github.com/biglinux/big-screen-monitor-display)
