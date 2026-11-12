"""Generate the Slides-artifact content files (project/deck.json + project/slides/*.html)."""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "deck"
(ROOT / "project" / "slides").mkdir(parents=True, exist_ok=True)

A = dict(spiva="99a7ca157f1ec4d5dff797b83915c3d0", quint="cb8985b74a17d7d7dee6c77d880a5ac6",
         event="989f9a50b90413912919a55b1c632ba0", regimes="551b82d101f844db8699bf3bff7bb8d1",
         cape="4773e8e384f71ec71d5a489954b3fb83", lev="7591298877b77b9172e239811ac4add1",
         equity="fd82fbfe31d8d8016f0638585540ec9c", alloc="6ca93dc8d344149ec1fafa96f678dabb",
         trials="20e28440d2b2c2b6fc5f8b8121ab7f64", timeline="239e44323689c57ae668320cfcc9a7a3")

DARK, LIGHT, ALT, INK2, BLUE, BLUE_D, ORANGE, RULE = (
    "#14213D", "#FBFBF8", "#F2F0EA", "#4A5568", "#2A78D6", "#1C5CAB", "#EB6834", "#DCD9CF")
HEAD = "'Space Grotesk', Arial, sans-serif"
TEXT = "Inter, Arial, sans-serif"
SLIDES = []


def img(key, w, h, alt):
    return f'<img src="/_blob/{A[key]}" alt="{alt}" style="width:{w}px;height:{h}px;object-fit:contain">'


def slide(sid, body, notes, bg=LIGHT, eyebrow=None, title=None, n=None, color=DARK, footer=True, extra_style=""):
    head = ""
    if eyebrow:
        head += (f'<p style="font-family:{HEAD};font-size:24px;font-weight:600;letter-spacing:2px;'
                 f'text-transform:uppercase;color:{BLUE_D if bg != DARK else "#8FB8EE"}">{eyebrow}</p>')
    if title:
        head += (f'<h2 style="font-family:{HEAD};font-size:56px;font-weight:600;line-height:1.1;'
                 f'color:{color}">{title}</h2>')
    hdr = f'<div style="display:flex;flex-direction:column;gap:12px">{head}</div>' if head else ""
    foot = ""
    if footer:
        fc = "#9AA3B5" if bg == DARK else "#6B7280"
        foot = (f'<p style="position:absolute;left:128px;bottom:56px;width:1664px;font-size:24px;color:{fc}">'
                f'Math 585 · Midterm · Buying Blood, Not Knives<span style="color:{fc}">  ·  {len(SLIDES) + 1}</span></p>')
    html = (f'<section id="{sid}" data-transition="fade" style="background:{bg};color:{color};font-family:{TEXT};'
            f'padding:104px 128px 150px;display:flex;flex-direction:column;gap:36px{extra_style}">'
            f'{hdr}{body}{foot}<aside>{notes}</aside></section>')
    SLIDES.append((sid, html))


def card(title, text, accent=BLUE, bg="#FFFFFF", w=None):
    ws = f"width:{w}px;" if w else "flex:1;"
    return (f'<div style="{ws}display:flex;flex-direction:column;gap:12px;background:{bg};padding:32px;'
            f'border:1px solid {RULE};border-top:6px solid {accent};border-radius:12px">'
            f'<h3 style="font-family:{HEAD};font-size:32px;font-weight:600;line-height:1.2;color:{DARK}">{title}</h3>'
            f'<p style="font-size:26px;line-height:1.4;color:{INK2}">{text}</p></div>')


def table(rows, widths, size=24, head_bg=DARK):
    out = f'<table style="font-family:{TEXT};font-size:{size}px;color:{DARK};width:1664px">'
    out += f'<tr style="background:{head_bg}">' + "".join(
        f'<th style="width:{w}%;color:{LIGHT};text-align:left">{c}</th>' for c, w in zip(rows[0], widths)) + "</tr>"
    for i, r in enumerate(rows[1:]):
        bg = "#FFFFFF" if i % 2 == 0 else ALT
        out += f'<tr style="background:{bg}">' + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
    return out + "</table>"


# 1 ─ cover
slide("cover", f'''
<div style="position:absolute;left:0;top:0;width:1920px;height:1080px;background:linear-gradient(135deg, {DARK} 0%, #1E3360 100%)"></div>
<div style="display:flex;flex-direction:column;gap:28px;width:1500px">
<p style="font-family:{HEAD};font-size:28px;font-weight:600;letter-spacing:3px;text-transform:uppercase;color:#F4A07E">Math 585 · Midterm presentation · November 16, 2026</p>
<h1 style="font-family:{HEAD};font-size:120px;font-weight:700;line-height:1.02;color:{LIGHT}">Buying blood,<br>not knives</h1>
<p style="font-size:40px;line-height:1.35;color:#C9D3E6;width:1400px">A fear-tranche strategy on broad Nasdaq / S&amp;P beta: hold dry powder, spend it — partly through 2x leverage — when fear is extreme, and rebuild it when greed returns.</p>
</div>
<div style="flex:1"></div>
<p style="font-size:28px;color:#C9D3E6">Group [__] · [Member 1] · [Member 2] · [Member 3]</p>
''', "Speaker: [Member 1]. One-sentence pitch: ordinary investors should own broad index beta; our edge is WHEN we add to it — buying in panics, scaling in, with leverage only at the extremes — and recycling the capital by trimming in greed.",
      bg=DARK, color=LIGHT, footer=False, extra_style=";justify-content:center")

# 2 ─ key messages
def stat(big, label, sub, col):
    return (f'<div style="flex:1;display:flex;flex-direction:column;gap:16px;padding:40px;background:#FFFFFF;'
            f'border:1px solid {RULE};border-radius:16px">'
            f'<p style="font-family:{HEAD};font-size:96px;font-weight:700;line-height:1;color:{col}">{big}</p>'
            f'<h3 style="font-family:{HEAD};font-size:32px;font-weight:600;line-height:1.25;color:{DARK}">{label}</h3>'
            f'<p style="font-size:24px;line-height:1.4;color:{INK2}">{sub}</p></div>')
slide("key", f'''<div style="display:flex;gap:32px;flex:1">
{stat("93%", "of active large-cap funds trail the S&amp;P 500 over 20 years", "SPIVA U.S. Year-End 2025. So the core of the portfolio is index beta: QQQM / VOO.", DARK)}
{stat("+33%", "average next-12-month QQQ return when bought on every VIX ≥ 30 day", "vs +13.5% for buying on any day (QQQ 1999–2026, 621 fear days). Fear is a measurable edge.", ORANGE)}
{stat("0.71", "Sharpe of our fixed-capital prototype, max drawdown −39%", "vs 0.64 and −52% for buy-and-hold 50/50 QQQ+SPY (2007–2026, costs in). Goal for the final: Sharpe ≥ 1.", BLUE_D)}
</div>''', "Speaker: [Member 1]. Key messages up front, per the rubric. (1) Why index beta. (2) Why fear signals. (3) What we have built and where it falls short: the prototype improves drawdown a lot and Sharpe a little; the rest of the semester is about the levers that should push Sharpe past 1.",
      eyebrow="Key messages", title="Own the index. Add to it when others panic. Recycle the cash.")

# 3 ─ why index
slide("why-index", f'''<div style="display:flex;gap:48px;align-items:start">
{img("spiva", 960, 546, "Bar chart: share of active large-cap funds trailing the S&P 500 — 79% (1y), 67% (3y), 89% (5y), 86% (10y), 90% (15y), 93% (20y)")}
<div style="flex:1;display:flex;flex-direction:column;gap:24px">
{card("Diversification (Lecture 9)", "With n weakly correlated stocks, volatility falls like 1/√n while expected return holds, so Sharpe grows with breadth.")}
{card("CAPM", "A single stock’s Sharpe ratio is below the market’s: idiosyncratic risk is not paid.")}
{card("For an individual", "QQQM / VOO: 0.15% / 0.03% fees, daily liquidity, no manager risk.")}
</div></div>''', "Speaker: [Member 1]. Lecture 9: diversification raises Sharpe roughly with sqrt(n); CAPM says single-stock Sharpe < market. SPIVA year-end 2025: 79% of active large-cap funds lagged in 2025 and ~93% over 20 years (survivorship-corrected). Conclusion: don't try to beat the index by stock picking — improve how and when you hold it.",
      eyebrow="Why broad index beta", title="The index is the Sharpe-efficient core that most professionals fail to beat")

# 4 ─ why fear
slide("why-fear", f'''<div style="display:flex;gap:40px;align-items:stretch">
<div style="width:620px;display:flex;flex-direction:column;justify-content:center;gap:24px;padding:48px;background:{DARK};border-radius:16px">
<p style="font-family:{HEAD};font-size:44px;font-weight:600;line-height:1.25;color:{LIGHT}">“Be fearful when others are greedy, and be greedy when others are fearful.”</p>
<p style="font-size:26px;color:#C9D3E6">— Warren Buffett, “Buy American. I Am.” New York Times, Oct 16, 2008</p>
</div>
<div style="flex:1;display:grid;grid-template-columns:1fr 1fr;gap:24px">
{card("Sentiment premium", "When investor sentiment is low, subsequent returns are high (Baker &amp; Wurgler, 2006).", ORANGE)}
{card("Fear gauge", "VIX / VXN spikes coincide with forced selling; implied vol overshoots (Whaley, 2000).", ORANGE)}
{card("Variance risk premium", "Implied minus realised variance predicts index returns (Bollerslev, Tauchen &amp; Zhou, 2009).", BLUE)}
{card("Valuation", "Cheap starting CAPE → higher 10-year returns (Campbell &amp; Shiller, 1998).", BLUE)}
</div></div>''', "Speaker: [Member 1]. Economic story: in panics, leveraged and forced sellers must sell, risk-bearing capacity is scarce, so the expected return for whoever supplies liquidity rises. That is the 'edge' — compensation for buying when it feels worst. Buffett's 2008 op-ed is the practitioner version. Next slides test it on our own data.",
      eyebrow="Why sentiment", title="Fear is a risk premium you can be paid for")

# 5 ─ quintiles
slide("ev-quintiles", f'''<div style="display:flex;gap:32px;align-items:start">
{img("quint", 1300, 628, "Seven panels of mean next-63-day QQQ return by signal quintile for VIX, VXN score, drawdown score, price-sentiment proxy, CNN Fear and Greed, variance risk premium and the composite; Q5 (fear) is above Q1 (calm) in every panel")}
<div style="flex:1;display:flex;flex-direction:column;gap:20px">
<p style="font-family:{HEAD};font-size:44px;font-weight:600;line-height:1.15;color:{DARK}">Q5 &gt; Q1 in all 7 signals</p>
<p style="font-size:26px;line-height:1.4;color:{INK2}">Composite IC +0.18 (block-bootstrap 5–95%: +0.04 to +0.33). VIX +0.20.</p>
<p style="font-size:26px;line-height:1.4;color:{INK2}">Bought at the <b>t+1 close</b>: no look-ahead.</p>
<p style="font-size:24px;line-height:1.4;color:{INK2}">CNN F&amp;G 2011–2023 only; VXN real data from 2008.</p>
</div></div>''', "Speaker: [Member 2]. Seven indicators, 2008–2026, oriented so higher = more fear. Each bar: average QQQ return over the next 63 trading days. Dashed line = unconditional mean (≈4.5%). The ordering is not perfectly monotone for drawdown/composite (Q4 > Q5) — deepest fear has fatter left tails — which is why we scale in rather than go all-in. IC confidence intervals use a 63-day moving-block bootstrap because forward returns overlap.",
      eyebrow="Evidence 1 · seven indicators", title="More fear today → higher Nasdaq returns over the next quarter")

# 6 ─ scale-in
slide("ev-scalein", f'''{img("event", 1664, 640, "Two panels: left, average cumulative QQQ return after buying on every extreme-fear day (+33% VIX≥30, +28% composite, +19% CNN) vs +13.5% any day; right, buying only the first day of each episode gives +11.5% to +23%")}''',
      "Speaker: [Member 2]. The design insight. Left: buy on EVERY extreme-fear day — average next-year QQQ return +33% (VIX≥30, 88% positive), +28% (composite top decile), +19% (CNN ≤20) vs +13.5% for any day. Right: buy only the FIRST day of each episode — barely better than random; VIX≥30 first days were worse (+11.5%), because the first day is often early in a crash (2008-09-15: −59% worst one-year path). So: tranches, spaced out by price, not one big bet.",
      eyebrow="Evidence 2 · design implication", title="The edge is in scaling in through the fear window, not catching day one")

# 7 ─ regimes + CAPE
slide("ev-regimes", f'''<div style="display:flex;gap:32px;align-items:start">
<div style="display:flex;flex-direction:column;gap:16px">{img("regimes", 830, 447, "Composite fear Q5 vs Q1 next-63-day QQQ return by period: 1999–2002 +7.2 vs −16.4; 2003–09 +4.3 vs +2.1; 2010–19 +7.7 vs +3.0; 2020–26 +5.8 vs +2.7")}
<p style="font-size:26px;line-height:1.4;color:{INK2};width:830px">Holds in every regime, including the dot-com bust. Pooled 1999–2026 IC is only 0.07: 2000–02 had three years of fear <i>and</i> falling prices.</p></div>
<div style="display:flex;flex-direction:column;gap:16px">{img("cape", 800, 530, "Scatter of Shiller CAPE vs next-10-year real S&P 500 return, 1881–2013 starts; rank correlation −0.49")}
<p style="font-size:26px;line-height:1.4;color:{INK2};width:800px">Valuation works on years, not weeks: our next step is a point-in-time forward-P/E term.</p></div>
</div>''', "Speaker: [Member 2]. Robustness. Within every sub-period the most-fearful quintile beats the calmest. But across periods it is a Simpson's-paradox story: 2000–02 was fearful for three years while QQQ fell 80%. Fear alone cannot tell a crash bottom from a valuation bust — that's why the dashboard carries a valuation term (35% weight) and why we add a trend guard. CAPE (Shiller data, 1881–2013 starts) shows valuation predicts 10-year returns (ρ = −0.49).",
      eyebrow="Evidence 3 · robustness", title="Fear beats calm in every regime — valuation guards the long horizon")

# 8 ─ DCA → fixed capital
def flow(cond, act, col):
    return (f'<div style="display:flex;gap:20px;align-items:center;padding:20px 28px;background:#FFFFFF;border:1px solid {RULE};border-left:8px solid {col};border-radius:10px">'
            f'<p style="width:640px;font-size:26px;line-height:1.35;color:{DARK}"><b>{cond}</b></p>'
            f'<x-shape kind="arrow-right" style="width:56px;height:28px;background:{col}"></x-shape>'
            f'<p style="flex:1;font-size:26px;line-height:1.35;color:{INK2}">{act}</p></div>')
def sleeve(name, pct, what, col):
    return (f'<div style="flex:1;display:flex;flex-direction:column;gap:8px;padding:28px;background:{col};border-radius:12px">'
            f'<p style="font-family:{HEAD};font-size:28px;font-weight:600;color:{LIGHT}">{name}</p>'
            f'<p style="font-family:{HEAD};font-size:56px;font-weight:700;line-height:1;color:{LIGHT}">{pct}</p>'
            f'<p style="font-size:24px;color:#E6ECF5">{what}</p></div>')
slide("design", f'''<div style="display:flex;gap:24px">
{sleeve("Core beta", "70%", "QQQM / VOO (half trend-guarded)", DARK)}
{sleeve("Dry powder", "30%", "T-bills: BIL / SGOV", "#4A5568")}
{sleeve("Leverage sleeve", "0–30%", "QLD · TQQQ · QQQ LEAPS calls", "#B4461C")}
</div>
<div style="display:flex;flex-direction:column;gap:14px">
{flow("Fear ≥ 80th percentile, price 8% below last buy", "Tranche: 7.5% of NAV from powder → core", BLUE)}
{flow("Fear ≥ 90th percentile AND VXN 15% off its 10-day high", "Leverage: 10% of NAV → QLD (cap 30%)", ORANGE)}
{flow("Fear back below median & QQQ &gt; MA200, or +60%, or 18 months", "Sell the sleeve → powder; surplus → core", "#6B7280")}
{flow("Greed ≤ 15th percentile & QQQ ≥ 1.08 × MA200", "Trim core back to 70%: rebuild the powder", "#6B7280")}
</div>''', "Speaker: [Member 3]. From DCA to a trading strategy. Mood-DCA needs new cash every month; the course gives us fixed capital. So we pre-fund the 'future contributions' as a 30% powder sleeve, spend it on fear, and — the new part — define SELL rules so capital recycles: the leverage sleeve is sold when fear normalises, and the core is trimmed back in greed. The fear percentile is causal (expanding window, ≥2 years of history).",
      eyebrow="Strategy · from DCA to fixed capital", title="Three sleeves, four rules: spend powder on fear, rebuild it in greed")

# 9 ─ rules table
rows = [["Component", "Specification"],
        ["Assets", "QQQ / QQQM, SPY / VOO (core) · QLD, TQQQ, QQQ LEAPS calls (leverage) · BIL / SGOV (powder)"],
        ["Signal", "Dashboard v4 composite: 30% fear (VXN level + 2-yr percentile, price-sentiment proxy) + 35% vol-adaptive drawdown + 35% valuation (pending point-in-time data) → expanding percentile"],
        ["Timing", "Daily. Signal at close t, order fills at t+1 (QC: next open). No intraday."],
        ["Costs", "5 bp per side ETFs, 15 bp leveraged ETFs; T-bill yield on cash; IBKR brokerage model on QC"],
        ["Risk limits", "Leverage sleeve ≤ 30% NAV (net exposure ≤ 1.3x); no shorting; half the core leaves QQQ below 0.97 × MA200"],
        ["Capital / live", "$100k paper on QuantConnect + IBKR paper; same code for backtest and live (qc/main.py)"]]
slide("rules", table(rows, [18, 82], size=26),
      "Speaker: [Member 3]. Every number on this slide is a QC parameter in qc/main.py, so we can run walk-forward tests and the live account from the same code. The valuation term is switched off in the backtest because our forward-P/E history uses realised EPS (look-ahead); a point-in-time version is TODO-4.",
      eyebrow="Strategy · specification", title="Asset classes, signal, execution and limits")

# 10 ─ leverage instruments
slide("leverage", f'''<div style="display:flex;gap:32px;align-items:start">
{img("lev", 1040, 550, "One-year return on capital vs QQQ return for 2x on margin, QLD at 20% and 40% path volatility, and a 0.77-delta 2-year LEAPS call sized to 2x delta: the LEAPS line flattens at about −54% in a crash while margin goes to −100%")}
<div style="flex:1;display:flex;flex-direction:column;gap:16px">
{card("No volatility decay", "A LEAPS call does not reset daily, so a choppy year costs time value, not compounding drag.", ORANGE)}
{card("Loss is capped", "Worst case is the premium: no margin call, no forced selling at the bottom.", ORANGE)}
{card("The catch", "Panic means high implied vol, so buy when VXN starts to recede; mark at bid/ask mid.", "#6B7280")}
</div></div>''', "Speaker: [Member 3]. Why QQQ LEAPS. Same starting 2x delta exposure, one-year horizon, BSM illustration (IV 22%, r 4%). Margin can go to −100% (margin call). QLD bleeds in choppy high-vol paths (green line). A deep-ish ITM LEAPS (delta ≈0.77, 2y) uses ~56% of capital for 2x exposure, keeps the rest in T-bills, and its loss flattens around −54% even if QQQ halves: defined risk, no forced sale at the bottom. Cost: time value and buying IV when it is expensive — hence the 'fear receding' entry trigger. Ayres & Nalebuff (Lifecycle Investing) make the same argument for young investors. Real-chain QC test is TODO-5.",
      eyebrow="Leverage · QLD vs TQQQ vs QQQ LEAPS", title="Same 2x exposure, different crash behaviour")

# 11 ─ equity curve
rows = [["2007-02 → 2026-09", "Sharpe", "CAGR", "Max DD"],
        ["B&amp;H 50/50 QQQ+SPY", "0.64", "12.8%", "−52%"],
        ["Static 70/30", "0.68", "11.9%", "−37%"],
        ["<b>v2 + QLD + trend</b>", "<b>0.71</b>", "11.8%", "<b>−39%</b>"],
        ["B&amp;H QQQ", "0.72", "16.2%", "−53%"]]
slide("bt-equity", f'''<div style="display:flex;gap:32px;align-items:start">
{img("equity", 1090, 650, "Equity and drawdown curves 2007–2026 for buy-and-hold 50/50, static 70/30, the strategy and buy-and-hold QQQ; strategy drawdown −39% vs −52%")}
<div style="flex:1;display:flex;flex-direction:column;gap:20px">
<table style="font-size:24px;color:{DARK}"><tr style="background:{DARK}"><th style="width:46%;color:{LIGHT}">{rows[0][0]}</th><th style="width:18%;color:{LIGHT};text-align:right">Sharpe</th><th style="width:18%;color:{LIGHT};text-align:right">CAGR</th><th style="width:18%;color:{LIGHT};text-align:right">Max DD</th></tr>
{"".join(f'<tr style="background:{"#FFFFFF" if i % 2 == 0 else ALT}"><td>{r[0]}</td><td style="text-align:right">{r[1]}</td><td style="text-align:right">{r[2]}</td><td style="text-align:right">{r[3]}</td></tr>' for i, r in enumerate(rows[1:]))}</table>
<p style="font-size:24px;line-height:1.4;color:{INK2}">Sharpe = excess return over T-bills. Leveraged ETFs before inception are synthetic: real vs synthetic TQQQ CAGR 42.15% vs 42.14% (2010–26).</p>
</div></div>''', "Speaker: [Member 3]. $100k fixed, 50/50 QQQ+SPY core as the VOO+QQQM stand-in. The strategy keeps the drawdown close to a static 70/30 while recovering faster after 2009 and 2022, because powder was spent near the lows. It does not beat QQQ buy-and-hold on CAGR — it holds less beta on average (0.74x). Sharpe edge over the static mix is small: 0.71 vs 0.68.",
      eyebrow="Backtest · fixed $100k", title="A quarter less drawdown than buy-and-hold, at similar Sharpe")

# 12 ─ allocation
def mini(big, txt):
    return (f'<div style="flex:1;display:flex;flex-direction:column;gap:8px;padding:24px 28px;background:#FFFFFF;border:1px solid {RULE};border-radius:12px">'
            f'<p style="font-family:{HEAD};font-size:48px;font-weight:700;line-height:1;color:{DARK}">{big}</p>'
            f'<p style="font-size:24px;line-height:1.35;color:{INK2}">{txt}</p></div>')
slide("bt-alloc", f'''{img("alloc", 1664, 548, "Stacked allocation 2007–2026: core, trend-guarded core, QLD sleeve and T-bills; powder spent in 2008–09, 2020 and 2022 and rebuilt afterwards; net exposure peaks near 1.25x")}
<div style="display:flex;gap:24px">{mini("0.74x", "average net equity exposure (QLD counted 2x)")}{mini("1.25x", "peak exposure, April 2020")}{mini("173", "trades in 19.6 years: about 9 a year")}</div>''',
      "Speaker: [Member 3]. Where the money is. The light grey band is powder. It is spent into 2008–09, 2020 and 2022 and rebuilt in the calm years by greed trims; the orange QLD sleeve appears only at the worst fear (January 2019, March 2020, May 2022 to April 2023, April 2025). Turnover is low (≈9 trades/yr), so costs and taxes are manageable.",
      eyebrow="Backtest · capital recycling", title="Powder is spent into 2008, 2020 and 2022, then rebuilt in greed")

# 13 ─ trial log
slide("trials", f'''{img("trials", 1664, 616, "Sharpe and max drawdown for all 12 variants in two samples; best is v2 + QLD + trend guard at 0.64 (QQQ core) and 0.71 (QQQ+SPY core); none above 1")}''',
      "Speaker: [Member 2]. Honesty slide. v1 rules were written down before any backtest; they failed to beat a static 70/30 because the powder ran out early in 2008. We made ONE diagnosed revision (v2: wider ladder, larger sleeve). Fear tranches alone don't raise Sharpe; adding the trend guard does, modestly. TQQQ adds nothing over QLD. Every variant stays in the trial count for the Deflated Sharpe Ratio. Sharpe > 1 is not reached yet — that is the plan for the final.",
      eyebrow="Backtest · every variant we ran", title="Pre-registered v1 failed; one diagnosed fix helped. Sharpe is still below 1")

# 14 ─ path to Sharpe > 1
rows = [["Lever", "Why it should raise Sharpe", "Test on QC"],
        ["Volatility-targeted core", "Cuts exposure when realised vol spikes; vol-managed portfolios raise Sharpe (Moreira &amp; Muir, 2017)", "15–20% vol target; fear sleeve buys on top"],
        ["Powder in IEF / GLD", "Diversifiers that usually rally in equity panics (not 2022)", "BIL vs IEF vs 50/50 IEF+GLD"],
        ["Credit &amp; term-structure filters", "HY OAS widening and VIX/VIX3M backwardation separate crashes from dips", "Incremental IC vs composite (t &gt; 2)"],
        ["Point-in-time valuation", "Restores the 35% valuation weight without look-ahead", "PIT forward P/E; IC by regime"],
        ["LEAPS instead of QLD", "Defined loss lets the sleeve be larger at the same tail risk", "Real chain, mid marks, ledger audit"],
        ["Anti-overfitting", "Pre-registration, walk-forward 2008–19 / 2020–26, Deflated Sharpe, PBO", "Report every trial"]]
slide("sharpe", table(rows, [24, 48, 28], size=24),
      "Speaker: [Member 2]. Sharpe is return over volatility; our signal mostly adds return in high-vol states, so it can't move Sharpe much alone. The remaining levers attack volatility (vol targeting, diversifying the powder) and tail risk (credit filter, LEAPS). Each lever is tested walk-forward with the trial count recorded; we will report Deflated Sharpe, not the best backtest.",
      eyebrow="Plan · Sharpe ≥ 1", title="Levers to push Sharpe past 1: lower volatility, not more leverage")

# 15 ─ risks
rows = [["Risk", "What could go wrong", "Mitigation"],
        ["Valuation bust (2000–02)", "Fear stays high for years while prices keep falling", "Trend guard on half the core; valuation term; tranche spacing −8%"],
        ["Leveraged-ETF decay", "QLD/TQQQ bleed in choppy, high-vol markets", "Enter only when VXN recedes; 18-month time stop; LEAPS alternative"],
        ["Regime change", "VXN lost predictive power after 2020 in the dashboard study", "Composite of many signals; re-test IC by sub-period"],
        ["Look-ahead in data", "Forward P/E used realised EPS; CNN timestamps are UTC midnight", "Point-in-time data only; shift CNN +1 day; t+1 execution"],
        ["Overfitting", "12 variants already; thresholds are fragile", "Pre-registration, walk-forward, Deflated Sharpe, PBO"],
        ["Execution / data", "QC fills, option marks, missing data", "Next-open fills, bid/ask mid, stale-mark audit, 1% cash buffer"]]
slide("risks", table(rows, [22, 40, 38], size=24),
      "Speaker: [Member 3]. Downside risk management: the biggest one is a 2000–02-style grind where 'cheap' keeps getting cheaper. Our answers: (1) half the core follows a 200-day trend rule and leaves in prolonged bear markets, (2) tranches are spaced 8% apart so powder lasts through a −40% decline, (3) leverage only after fear starts to recede, with a hard cap and time stop.",
      eyebrow="Risks", title="What we expect to go wrong, and what we do about it")

# 16 ─ project plan
rows = [["Week", "Dates", "Milestones", "Owner"],
        ["0", "Nov 11–16", "<b>Midterm presentation Nov 16</b> · QC probe &amp; signal parity (TODO-0) · paper account set up", "All · [M3]"],
        ["1", "Nov 17–23", "<b>Live paper trading starts Nov 17 (v2 + QLD)</b> · new-indicator ICs on QC (HY OAS, VIX term, AAII, put/call)", "[M3] · [M2]"],
        ["2", "Nov 24–30", "Sharpe levers walk-forward (vol target, powder in IEF/GLD) · LEAPS chain audit · Thanksgiving buffer", "[M1] · [M3]"],
        ["3", "Dec 1–7", "Freeze v3 on Dec 3 → second paper account · Deflated Sharpe, PBO on all trials", "[M1] · [M2]"],
        ["4", "Dec 8–15", "≈20 trading days of live results vs backtest · final report &amp; presentation", "All"]]
slide("plan", table(rows, [8, 14, 62, 16], size=26) + f'''
<p style="font-size:24px;line-height:1.4;color:{INK2}">Cushion: two buffer days per week. If QC option data fails the audit, the sleeve stays QLD. Final due date assumed mid-December: [confirm].</p>''',
      "Speaker: [Member 1]. Live paper trading must start next week to get roughly a month of live results. v2 goes live as-is (no more tuning) so the live month is a true out-of-sample test; improvements go into v3, frozen Dec 3 and run in parallel. Note: QQQ is ~11% below its Oct 6 high as of Nov 10 — the live window is likely to start in a pullback, which will exercise the tranche rules.",
      eyebrow="Project plan", title="Five weeks, live trading from November 17")

# 17 ─ team
def role(name, what, slides):
    return (f'<div style="flex:1;display:flex;flex-direction:column;gap:14px;padding:32px;background:#FFFFFF;border:1px solid {RULE};border-top:6px solid {BLUE};border-radius:12px">'
            f'<h3 style="font-family:{HEAD};font-size:36px;font-weight:600;color:{DARK}">{name}</h3>'
            f'<p style="font-size:26px;line-height:1.4;color:{INK2}">{what}</p>'
            f'<p style="font-size:24px;color:{BLUE_D}"><b>Presents: {slides}</b></p></div>')
slide("team", f'''<div style="display:flex;gap:28px;flex:1">
{role("[Member 1]", "Thesis and signal design; Sharpe levers (vol targeting, powder assets); project lead", "slides 1–4, 16–17")}
{role("[Member 2]", "Evidence and statistics: IC, bootstrap, new indicators on QC, trial log, Deflated Sharpe", "slides 5–7, 13–14")}
{role("[Member 3]", "Strategy rules and QuantConnect implementation, leverage and LEAPS, risk, live paper trading", "slides 8–12, 15")}
</div>''', "Speaker: [Member 1] closes and opens Q&A. Replace the placeholders with names.",
      eyebrow="Team", title="Who does what — and who presents it")

# 18 ─ references
refs = ["S&amp;P Dow Jones Indices (2026). SPIVA U.S. Scorecard, Year-End 2025.",
        "Ye, D. (2026). Math 585 Lecture 9: Portfolio and diversification of risks; CAPM.",
        "Buffett, W. (2008). Buy American. I Am. The New York Times, Oct 16.",
        "Baker, M. &amp; Wurgler, J. (2006). Investor sentiment and the cross-section of stock returns. Journal of Finance.",
        "Whaley, R. (2000). The investor fear gauge. Journal of Portfolio Management.",
        "Bollerslev, T., Tauchen, G. &amp; Zhou, H. (2009). Expected stock returns and variance risk premia. Review of Financial Studies.",
        "Campbell, J. &amp; Shiller, R. (1998). Valuation ratios and the long-run stock market outlook. Journal of Portfolio Management.",
        "Moreira, A. &amp; Muir, T. (2017). Volatility-managed portfolios. Journal of Finance.",
        "Cheng, M. &amp; Madhavan, A. (2009). The dynamics of leveraged and inverse ETFs. Journal of Investment Management.",
        "Ayres, I. &amp; Nalebuff, B. (2010). Lifecycle Investing. Basic Books.",
        "Bailey, D. &amp; López de Prado, M. (2014). The deflated Sharpe ratio. Journal of Portfolio Management.",
        "Data: QuantConnect (QQQ, SPY, VXN, TQQQ) · CBOE VIX (github.com/datasets/finance-vix) · CNN Fear &amp; Greed archive (github.com/Benny2000/fear-greed-data) · Shiller data · code: github.com/davidwang0116/nasdaq-mood-dashboard"]
slide("refs", f'''<div style="display:grid;grid-template-columns:1fr 1fr;gap:18px 48px">{"".join(f'<p style="font-size:24px;line-height:1.35;color:{INK2}">{r}</p>' for r in refs)}</div>''',
      "Reference list. Backtests are historical simulations, not investment advice.",
      bg=ALT, eyebrow="References", title="Sources")

order = [s for s, _ in SLIDES]
for sid, html in SLIDES:
    (ROOT / "project" / "slides" / f"{sid}.html").write_text(html, encoding="utf-8")
deck = {"v": 4, "createdOnFiles": {"v": 1, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "lists": "css", "title": "Buying Blood, Not Knives — Math 585 Midterm", "order": order,
        "sections": {"s1": {"description": "Thesis: own the index, add to it in fear", "start": "cover"},
                     "s2": {"description": "Evidence that fear predicts higher index returns", "start": "ev-quintiles"},
                     "s3": {"description": "Strategy: from DCA to a fixed-capital rule set with leverage", "start": "design"},
                     "s4": {"description": "Backtest results and the honest trial log", "start": "bt-equity"},
                     "s5": {"description": "Path to Sharpe ≥ 1, risks, plan and team", "start": "sharpe"}},
        "cover": "cover",
        "faces": {"space-grotesk": {"family": "Space Grotesk", "href": "https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300..700&display=swap"},
                  "inter": {"family": "Inter", "href": "https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap"}},
        "designSystems": []}
(ROOT / "project" / "deck.json").write_text(json.dumps(deck, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(order), "slides:", order)
