"""Universal display engine: protocol-family drivers, registry and discovery.

``registry`` lists the supported families and how to recognise them,
``discovery`` turns USB identifiers into candidates (sysfs only, nothing is
written to a device) and one module per family implements the driver
contract described in ``base``.
"""
