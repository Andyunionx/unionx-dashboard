"""Carga offline de ventas (CMR, SAWA, Walmart Fulfillment, etc.)."""
import streamlit as st


def render():
    # Reutilizar el módulo existente que ya tiene la lógica
    from dashboard_carga_offline import render_carga_offline_tab
    render_carga_offline_tab()
