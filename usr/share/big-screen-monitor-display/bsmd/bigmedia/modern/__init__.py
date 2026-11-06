"""Big Media Player — Modern Collection: eight modern skins on the same engine.

Each skin is an original design that follows the composition of one modern
player style (see docs/big-media-player-modern.md). Covers come only from
the MPRIS player; every symbol, material and texture is drawn procedurally.
"""

from .ember import BigEmber
from .flow import BigFlow
from .groove import BigGroove
from .lounge import BigLounge
from .pure import BigPure
from .stage import BigStage
from .vinyl import BigVinyl
from .wave import BigWave

MODERN_SKINS = (BigVinyl, BigPure, BigEmber, BigGroove, BigLounge, BigWave, BigFlow, BigStage)
