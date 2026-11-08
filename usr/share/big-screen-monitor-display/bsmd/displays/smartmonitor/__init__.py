"""SmartMonitor 3.5" HID panel (llhmi.com / llTechCo, USB 0483:0065).

Sold as "3.5 inch PC CPU Data Monitor" under many brands. It is not a
framebuffer: it renders a theme stored in its flash and receives numbers on
channels. :mod:`.layout` designs the dashboard, :mod:`.imgdat` compiles it,
:mod:`.protocol` holds the wire format and :mod:`.driver` drives the panel.
"""
