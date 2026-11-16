# -*- coding: utf-8 -*-
"""Funções utilitárias comuns."""

from typing import Union


def celsius_to_fahrenheit(temp_celsius: float) -> int:
    """Converte temperatura de Celsius para Fahrenheit."""
    return round((temp_celsius * 9 / 5) + 32)


def format_temperature(temp_celsius: float, unit: str = 'C') -> tuple[int, str]:
    """Formata temperatura para exibição na unidade especificada."""
    if unit == 'F':
        return (celsius_to_fahrenheit(temp_celsius), '°F')
    return (round(temp_celsius), '°C')


def validate_temperature_unit(unit: str) -> bool:
    """Valida se a unidade de temperatura é válida."""
    return unit in ('C', 'F')


def validate_display_mode(mode: str) -> bool:
    """Valida se o modo de exibição é válido."""
    return mode in ('auto', 'temp', 'util')


def clamp(value: Union[int, float], min_value: Union[int, float], 
          max_value: Union[int, float]) -> Union[int, float]:
    """Limita um valor entre um mínimo e máximo."""
    return max(min_value, min(value, max_value))
