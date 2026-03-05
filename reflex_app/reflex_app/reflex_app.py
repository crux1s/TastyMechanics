import reflex as rx
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os
import base64
import io

from .ingestion import parse_csv, validate_columns
from .mechanics import compute_app_data, calculate_windowed_equity_pnl, _aggregate_campaign_pnl, calculate_daily_realized_pnl
from .config import COLOURS, INCOME_SUB_TYPES, OPT_TYPES, TRADE_TYPES
from .ui_components import fmt_dollar

class State(rx.State):
    has_data: bool = False
    filename: str = ""

    total_realized_pnl: float = 0.0
    window_realized_pnl: float = 0.0
    realized_ror: str = "N/A"
    capital_deployed: float = 0.0
    cap_efficiency: str = "N/A"

    selected_period: str = "All Time"
    time_options: list[str] = ["YTD", "Last 7 Days", "Last Month", "Last 3 Months", "Half Year", "1 Year", "All Time"]

    _parsed_data = None
    _df = None
    _app_data = None

    async def handle_upload(self, files: list[rx.UploadFile]):
        for file in files:
            upload_data = await file.read()
            self.filename = file.filename

            # Basic validation
            missing = validate_columns(upload_data)
            if missing:
                return rx.window_alert(f"Missing columns: {', '.join(missing)}")

            try:
                self._parsed_data = parse_csv(upload_data)
                self._df = self._parsed_data.df
                self.has_data = True
                self.update_dashboard()
            except Exception as e:
                import traceback
                print(traceback.format_exc())
                return rx.window_alert(f"Error parsing CSV: {str(e)}")

    def set_period(self, period: str):
        self.selected_period = period
        if self.has_data:
            self.update_dashboard()

    def update_dashboard(self):
        if self._df is None:
            return

        latest_date = self._df['Date'].max()

        # Build AppData (campaigns etc)
        self._app_data = compute_app_data(self._parsed_data, False)

        # All time stats
        total_pnl = self._app_data.closed_camp_pnl + self._app_data.open_premiums_banked + self._app_data.pure_opts_pnl
        all_time_income = self._df[self._df['Sub Type'].isin(INCOME_SUB_TYPES)]['Total'].sum()
        wheel_divs = sum(c.dividends for camps in self._app_data.all_campaigns.values() for c in camps)
        self.total_realized_pnl = total_pnl + all_time_income - wheel_divs

        # Window stats
        start_date = self.get_start_date(latest_date)
        df_window = self._df[self._df['Date'] >= start_date]

        w_opts = df_window[df_window['Instrument Type'].isin(OPT_TYPES) & (df_window['Type'].isin(TRADE_TYPES))]
        eq_pnl = calculate_windowed_equity_pnl(self._df, start_date)
        w_income = df_window[df_window['Sub Type'].isin(INCOME_SUB_TYPES)]['Total'].sum()

        self.window_realized_pnl = w_opts['Total'].sum() + eq_pnl + w_income

        # ROR
        total_deposited = self._df[self._df['Sub Type']=='Deposit']['Total'].sum()
        total_withdrawn = self._df[self._df['Sub Type']=='Withdrawal']['Total'].sum()
        net_deposited = total_deposited + total_withdrawn
        if net_deposited > 0:
            self.realized_ror = f"{(self.total_realized_pnl / net_deposited * 100):.1f}%"
        else:
            self.realized_ror = "N/A"

        # Capital Efficiency
        self.capital_deployed = self._app_data.capital_deployed + self._app_data.extra_capital_deployed
        window_days = max((latest_date - start_date).days, 1)
        pnl_to_use = self.total_realized_pnl if self.selected_period == "All Time" else self.window_realized_pnl

        if self.capital_deployed > 0:
            eff = (pnl_to_use / self.capital_deployed / window_days * 365 * 100)
            self.cap_efficiency = f"{eff:.1f}%"
        else:
            self.cap_efficiency = "N/A"

    def get_start_date(self, latest_date):
        if self.selected_period == "All Time": return self._df['Date'].min()
        if self.selected_period == "YTD": return pd.Timestamp(latest_date.year, 1, 1)
        if self.selected_period == "Last 7 Days": return latest_date - timedelta(days=7)
        if self.selected_period == "Last Month": return latest_date - timedelta(days=30)
        if self.selected_period == "Last 3 Months": return latest_date - timedelta(days=90)
        if self.selected_period == "Half Year": return latest_date - timedelta(days=182)
        if self.selected_period == "1 Year": return latest_date - timedelta(days=365)
        return self._df['Date'].min()

    @rx.var
    def pnl_display(self) -> str:
        val = self.total_realized_pnl if self.selected_period == "All Time" else self.window_realized_pnl
        return fmt_dollar(val)

    @rx.var
    def pnl_color(self) -> str:
        val = self.total_realized_pnl if self.selected_period == "All Time" else self.window_realized_pnl
        return "#00cc96" if val >= 0 else "#ff5252"

    @rx.var
    def capital_deployed_display(self) -> str:
        return fmt_dollar(self.capital_deployed)

    @rx.var
    def equity_curve_chart(self) -> go.Figure:
        if not self.has_data or self._df is None:
            return go.Figure()

        latest_date = self._df['Date'].max()
        start_date = self.get_start_date(latest_date)

        daily_pnl = calculate_daily_realized_pnl(self._df, start_date)
        if daily_pnl.empty:
            return go.Figure()

        daily_pnl = daily_pnl.sort_values('Date')
        daily_pnl['Cumulative'] = daily_pnl['PnL'].cumsum()

        fig = go.Figure(data=[go.Scatter(
            x=daily_pnl['Date'],
            y=daily_pnl['Cumulative'],
            line=dict(color="#00cc96", width=2),
            fill='tozeroy',
            fillcolor='rgba(0, 204, 150, 0.1)'
        )])

        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color="#8b949e", size=10),
            margin=dict(l=40, r=20, t=20, b=40),
            height=350,
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=True, gridcolor="#1f2937", zeroline=False),
        )
        return fig

def metric_card(label, value, help_text, color="#00cc96"):
    return rx.vstack(
        rx.text(label, color="#8b949e", font_size="0.75rem", text_transform="uppercase", letter_spacing="0.05em", font_weight="600"),
        rx.text(value, color=color, font_size="1.5rem", font_weight="700", font_family="IBM Plex Mono, monospace"),
        rx.text(help_text, color="#484f58", font_size="0.7rem"),
        background_color="#111827",
        padding="1.5rem",
        border_radius="12px",
        border="1px solid #1f2937",
        align_items="start",
        width="100%",
        transition="transform 0.2s",
        _hover={"transform": "translateY(-2px)", "border_color": "#3b82f6"},
    )

def sidebar():
    return rx.vstack(
        rx.hbox(
            rx.image(src="/icon.png", width="30px", height="30px"),
            rx.heading("TastyMechanics", size="6", color="white"),
            spacing="3",
            align_items="center",
            margin_bottom="2.5rem",
        ),
        rx.vstack(
            rx.button(rx.hbox(rx.icon(tag="layout-dashboard", size=18), rx.text("Dashboard")), variant="soft", width="100%", justify_content="start", color_scheme="blue"),
            rx.button(rx.hbox(rx.icon(tag="activity", size=18), rx.text("Open Positions")), variant="ghost", width="100%", justify_content="start", color="gray"),
            rx.button(rx.hbox(rx.icon(tag="trending-up", size=18), rx.text("Performance")), variant="ghost", width="100%", justify_content="start", color="gray"),
            rx.button(rx.hbox(rx.icon(tag="microscope", size=18), rx.text("Trade Analysis")), variant="ghost", width="100%", justify_content="start", color="gray"),
            rx.button(rx.hbox(rx.icon(tag="target", size=18), rx.text("Wheel Campaigns")), variant="ghost", width="100%", justify_content="start", color="gray"),
            align_items="start",
            width="100%",
            spacing="1",
        ),
        rx.spacer(),
        rx.upload(
            rx.vstack(
                rx.icon(tag="upload", color="#3b82f6", size=24),
                rx.text("Upload CSV", font_size="0.9rem", color="white", font_weight="600"),
                rx.text("TastyTrade export", font_size="0.75rem", color="gray"),
                spacing="1",
            ),
            id="upload_csv",
            border="1px dashed #30363d",
            padding="1.5rem",
            border_radius="12px",
            on_drop=State.handle_upload(rx.upload_files(upload_id="upload_csv")),
            _hover={"border_color": "#3b82f6", "bg": "rgba(59, 130, 246, 0.05)"},
            width="100%",
        ),
        padding="2rem",
        width="260px",
        height="100vh",
        background_color="#0d1117",
        border_right="1px solid #30363d",
        position="fixed",
        left="0",
        top="0",
        z_index="10",
    )

def index() -> rx.Component:
    return rx.hbox(
        sidebar(),
        rx.box(
            rx.vstack(
                rx.hbox(
                    rx.vstack(
                        rx.heading(f"Portfolio Overview", size="7", color="white"),
                        rx.text("Real-time performance metrics and equity tracking", color="#8b949e", font_size="0.9rem"),
                        align_items="start",
                        spacing="1",
                    ),
                    rx.spacer(),
                    rx.select(
                        State.time_options,
                        value=State.selected_period,
                        on_change=State.set_period,
                        color="white",
                        bg="#161b22",
                        border_color="#30363d",
                        border_radius="8px",
                    ),
                    width="100%",
                    padding_bottom="2.5rem",
                    align_items="center",
                ),
                rx.cond(
                    State.has_data,
                    rx.vstack(
                        rx.grid(
                            metric_card("Realized P/L", State.pnl_display, "Total banked profit/loss", color=State.pnl_color),
                            metric_card("Realized ROR", State.realized_ror, "Return on net deposits"),
                            metric_card("Cap Efficiency", State.cap_efficiency, "Annualized capital utilization"),
                            metric_card("Capital Deployed", State.capital_deployed_display, "Current share exposure"),
                            columns="4",
                            spacing="5",
                            width="100%",
                        ),
                        rx.box(
                            rx.vstack(
                                rx.hbox(
                                    rx.heading("Equity Curve", size="4", color="white"),
                                    rx.spacer(),
                                    rx.badge("Realized", color_scheme="green", variant="surface"),
                                    width="100%",
                                    margin_bottom="1.5rem",
                                ),
                                rx.plotly(data=State.equity_curve_chart),
                                width="100%",
                            ),
                            width="100%",
                            background_color="#111827",
                            padding="2rem",
                            border_radius="16px",
                            border="1px solid #1f2937",
                            margin_top="2rem",
                        ),
                        width="100%",
                    ),
                    rx.center(
                        rx.vstack(
                            rx.icon(tag="file-up", size=48, color="#30363d"),
                            rx.text("No data loaded", font_size="1.2rem", color="white", font_weight="600"),
                            rx.text("Upload your TastyTrade CSV to populate the dashboard", color="#8b949e"),
                            spacing="2",
                        ),
                        height="60vh",
                        width="100%",
                    )
                ),
                max_width="1200px",
                margin="0 auto",
                width="100%",
            ),
            padding="3rem",
            width="100%",
            margin_left="260px",
            background_color="#0a0e17",
            min_height="100vh",
        ),
        width="100%",
        font_family="IBM Plex Sans, sans-serif",
    )

app = rx.App(
    stylesheets=[
        "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap",
    ],
)
app.add_page(index)
