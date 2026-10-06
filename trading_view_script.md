//@version=5
// dynamic_requests=true is REQUIRED: it lets request.security() accept a symbol
// string that we build at runtime from the Strike / Expiry dropdowns below.
// (In Pine v5 dynamic requests are off by default, so a concatenated symbol
// string would be rejected as "series string".)
indicator("Multi-Strike Option Combo + Call/Put Charts (VWAP/EMA/Supertrend)", overlay=true, max_bars_back=500, dynamic_requests=true)

// ============================================================
// HOW STRIKE SELECTION WORKS
//
// Mode "Dropdowns"        -> symbol is BUILT for you from dropdowns:
//                            Exchange + Root (shared)
//                            Expiry + CE/PE + Strike (PER LEG)
//                            Expiry = "YYYY-MM" dropdown + day dropdown
//                            Strike = "Strike" dropdown + "+" dropdown
//                            e.g. 25000 + 50  ->  25050
// Mode "Symbol"           -> the Strike and Expiry dropdowns are IGNORED and
//                            each leg's Symbol text field is used instead.
//                            If the dropdowns seem to do nothing, check this.
//
// Because expiry is per leg you can build:
//   Straddle          : same expiry, same strike, Leg1 CE + Leg2 PE
//   Strangle          : same expiry, different strikes, CE + PE
//   Calendar straddle : different expiry per leg, same strike
//   Calendar strangle : different expiry per leg, different strikes
// Contract > "Same expiry, all legs" keeps normal (non-calendar)
// setups quick: set the expiry once on Leg 1. Turn it OFF for calendars.
//
// STRIKE STEP
// Pine dropdown lists are fixed at compile time, so the list cannot be
// rebuilt per index. Instead the chosen strike is SNAPPED to the index
// strike step, so only strikes that really exist get requested:
//   NIFTY / FINNIFTY 50, BANKNIFTY / SENSEX / BANKEX 100, MIDCPNIFTY 25.
// Override it with Contract > "Strike step".
//
// Supported symbol formats:
//   New : NSE:NIFTY261229C25000    (YYMMDD + C/P + strike)
//   Old : NSE:NIFTY29DEC2625000CE  (DDMMMYY + strike + CE/PE)
//
// The Old format builder always zero-pads the day (07JUL26). If your broker
// feed uses 7JUL26 instead, switch Source to "Symbol" for that leg.
//
// Invalid strike/expiry combos do NOT break the script
// (ignore_invalid_symbol=true -> that leg is simply skipped).
// Turn on Table > "Symbol check" to see the exact symbol each leg requested.
//
// DO NOT change the per-leg "Symbol" fields back to input.symbol(). That looks
// tidier but TradingView resolves an input.symbol() value in the data layer on
// every leg, whether or not the script uses it, and Pine cannot suppress that.
// One expired contract sitting in an unused leg then kills the whole script
// with "Invalid symbol: This symbol doesn't exist". ignore_invalid_symbol only
// covers request.security(), not input resolution. Since every option contract
// expires eventually, a validated symbol input is a time bomb here. Plain text
// inputs degrade to "NO DATA" in the Symbol check table instead.
//
// ------------------------------------------------------------
// MOBILE LAYOUT
// The settings dialog has no horizontal scroll on phones: if any row is wider
// than the screen the whole dialog overflows and the OK button ends up off to
// the right, past Cancel, where it cannot be tapped. Pine gives no control
// over dialog width, so the only lever is keeping every row narrow.
// What actually drives row width, measured off a phone screenshot:
//   - NUMBER of controls in the row. This is by far the biggest factor. A
//     dropdown is a fixed ~115px no matter what it contains.
//   - LENGTH of the row's label text.
//   - DEFAULT VALUE of a text input. Text boxes are drawn to fit their
//     default, so "Custom root" (empty) came out at ~126px while the per-leg
//     "Symbol" field with a 21 character ticker came out at ~223px. That is
//     why the Symbol defaults are deliberately left empty.
//   - NOT the length of dropdown option strings. Dropdowns are fixed width
//     and truncate instead of growing, which is how "Symbol Picker" ended up
//     displaying as "Symbol ...". Option text can stay readable, but it must
//     still be short enough to READ when truncated, which is why the mode
//     names are just "Dropdowns" / "Symbol".
//
// Rules followed here, please keep to them when adding inputs:
//   - at most 2 controls per inline row (the "On / CE / Buy" rows are 3, but
//     a checkbox plus two 4-character dropdowns stays well inside the width)
//   - short titles, with the explanation in a tooltip rather than the label
//   - leave text input defaults empty unless the default is genuinely short
//   - anything wide gets its own row (Strike step, ST ATR, table positions)
// Expiry is one "YYYY-MM" dropdown plus a day dropdown for this reason. Three
// separate Y / M / D dropdowns on one row was what pushed OK off screen.
//
// Pine cannot size, scroll or re-flow the settings dialog. Content width is
// the only lever available, so if OK is still unreachable the remaining
// options are outside the script: rotate to landscape, or open the chart in a
// desktop-mode browser tab.
//
// ------------------------------------------------------------
// BAR RANGE (why wicks need care)
// A combo's open and close are exact: every leg is sampled at the same
// instant. Its high and low are not available anywhere and must be inferred.
// Adding up each leg's own high assumes all legs peaked on the same tick. For
// a straddle the call peaks when the put bottoms, so that pairing describes a
// moment that never happened and the wicks come out several times too long.
// Combo Chart > "Bar range" = "Spot linked" instead values the whole combo
// twice, once with the underlying at its bar high and once at its bar low,
// which is where the real extremes sit. Worked example, 25000 straddle:
//   sum of leg extremes 118 - 258   (range 140, wrong)
//   spot linked         180 - 196   (range 16, matches the real path)
// Known gap: for a straddle that crosses its strike mid-bar the true low sits
// at the strike rather than at either end of the spot range, so the low can be
// slightly understated. It never invents an extreme, which is the point.
//
// ------------------------------------------------------------
// SCALES (combo vs call/put price gap)
// Pine cannot pin an individual plot to the left or right scale. Only a
// whole indicator can be pinned (chart UI, or the `scale` argument of
// indicator()). Two ways to deal with the price gap:
//
//   1. One instance (default): use group "Call/Put Scaling" to pull the
//      call and put lines into the combo price band. Mode "Auto fit"
//      tracks the combo level, "Manual" is a fixed multiplier that keeps
//      the shape exactly. Real un-scaled prices always stay in the table.
//
//   2. True dual scale: add this indicator to the chart TWICE.
//      Copy A -> Combo Chart on, Call + Put off  -> pin to Right scale.
//      Copy B -> Combo off, Call + Put on        -> pin to Left scale.
//      Pin via right-click on the indicator > "Pin to left/right scale".
// ============================================================

// ============================================================
// HELPERS
// ============================================================
f_getLotSize(sym) =>
    s = str.upper(sym)
    str.contains(s, "BANKNIFTY") ? 30 : str.contains(s, "MIDCPNIFTY") ? 120 : str.contains(s, "FINNIFTY") ? 65 : str.contains(s, "NIFTY") ? 65 : str.contains(s, "SENSEX") ? 20 : str.contains(s, "BANKEX") ? 30 : 1

// text size dropdown -> size.* constant
f_textSize(t) =>
    t == "Tiny" ? size.tiny : t == "Small" ? size.small : t == "Normal" ? size.normal : t == "Large" ? size.large : size.huge

// table position dropdown -> position.* constant
f_tblPos(p) =>
    p == "Top Left" ? position.top_left : p == "Top Center" ? position.top_center : p == "Top Right" ? position.top_right : p == "Middle Left" ? position.middle_left : p == "Middle Center" ? position.middle_center : p == "Middle Right" ? position.middle_right : p == "Bottom Left" ? position.bottom_left : p == "Bottom Center" ? position.bottom_center : position.bottom_right

// NOTE: strike snapping and symbol assembly are deliberately written inline
// in the "BUILD LEG SYMBOLS" section rather than as helper functions here.
// Passing a symbol through a user-defined function can promote it to
// "series string", which request.security() rejects in Pine v5.

// Parse strike + Call/Put out of a symbol (used in Symbol mode)
f_parseOptionInfo(sym) =>
    s = str.upper(sym)
    n = str.length(s)
    last2 = n >= 2 ? str.substring(s, n - 2, n) : ""
    isOldStyle = last2 == "CE" or last2 == "PE"
    oldTypeChar = isOldStyle ? str.substring(s, n - 2, n - 1) : ""
    coreStr = isOldStyle ? str.substring(s, 0, n - 2) : s
    coreLen = str.length(coreStr)
    digitStart = coreLen
    for i = coreLen - 1 to 0
        ch = str.substring(coreStr, i, i + 1)
        isDigit = ch == "0" or ch == "1" or ch == "2" or ch == "3" or ch == "4" or ch == "5" or ch == "6" or ch == "7" or ch == "8" or ch == "9"
        if isDigit
            digitStart := i
        else
            break
    strikeStr = digitStart < coreLen ? str.substring(coreStr, digitStart, coreLen) : ""
    strikeVal = strikeStr == "" ? na : str.tonumber(strikeStr)
    newTypeChar = (not isOldStyle) and digitStart > 0 ? str.substring(coreStr, digitStart - 1, digitStart) : ""
    typeChar = isOldStyle ? oldTypeChar : newTypeChar
    optType = typeChar == "C" ? "Call" : typeChar == "P" ? "Put" : "N/A"
    [strikeVal, optType]

// na-safe weighted values. If a leg is off or its data is missing -> contributes 0.
f_w(ok, sgn, qty, v)      => ok and not na(v) ? sgn * qty * v : 0.0

// Widest possible pairing: every leg at its own best case. This is the old
// behaviour and it overstates the range, because it assumes each leg hit its
// extreme at the same instant even when they move in opposite directions.
f_wHigh(ok, sgn, qty, h, l) => not ok or na(h) or na(l) ? 0.0 : (sgn > 0 ? qty * h : -qty * l)
f_wLow(ok, sgn, qty, h, l)  => not ok or na(h) or na(l) ? 0.0 : (sgn > 0 ? qty * l : -qty * h)

// Spot-linked pairing. All legs share one underlying, so their extremes happen
// at the same moment: when spot peaks every call is at its high and every put
// at its low, and at the spot low the reverse. Evaluating the whole combo at
// those two moments gives a range it could actually have traded.
f_atSpotHi(ok, sgn, qty, isCall, h, l) => not ok or na(h) or na(l) ? 0.0 : sgn * qty * (isCall ? h : l)
f_atSpotLo(ok, sgn, qty, isCall, h, l) => not ok or na(h) or na(l) ? 0.0 : sgn * qty * (isCall ? l : h)

// ============================================================
// 1. CONTRACT  (underlying only - expiry and strike live on each leg)
// ============================================================
grpC = "1. Contract"
symMode = input.string("Dropdowns", "Source", options=["Dropdowns", "Symbol"], group=grpC, tooltip="Dropdowns = the symbol is built from Exchange + Root here plus each leg's own Expiry, CE/PE and Strike. This is the normal setting.\n\nSymbol = the per-leg Strike and Expiry dropdowns are IGNORED and the leg's Symbol text field is used instead. Only pick this if you are pasting exact tickers.")
symFmt  = input.string("New", "Format", options=["New", "Old"], group=grpC, tooltip="Leave this on New. New is the format TradingView actually serves today, verified live: NSE:NIFTY261229C25000.\n\nOld (NSE:NIFTY29DEC2625000CE) is a legacy layout that most feeds no longer resolve. Switching to Old will usually give NO DATA on every leg.")
exch    = input.string("NSE", "Exch", options=["NSE", "BSE", "MCX"], inline="c1", group=grpC)
root    = input.string("NIFTY", "", options=["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX", "CUSTOM"], inline="c1", group=grpC)
rootCus = input.string("", "Custom root", group=grpC, tooltip="Only used when Root = CUSTOM. Example: RELIANCE")
sameExp = input.bool(true, "Same expiry, all legs", group=grpC, tooltip="ON  = straddle / strangle (one expiry for the whole combo, set it on Leg 1).\nOFF = calendar straddle / strangle (each leg keeps its own expiry).")
stepIn  = input.string("Auto", "Strike step", options=["Auto", "25", "50", "100", "500"], group=grpC, tooltip="Strikes are snapped to this step so only real strikes get requested.\nAuto: NIFTY / FINNIFTY 50, BANKNIFTY / NIFTYNXT50 / SENSEX / BANKEX 100, MIDCPNIFTY 25.")

rootFinal = root == "CUSTOM" ? str.upper(rootCus) : root

autoStep   = rootFinal == "BANKNIFTY" or rootFinal == "SENSEX" or rootFinal == "BANKEX" or rootFinal == "NIFTYNXT50" ? 100 : rootFinal == "MIDCPNIFTY" ? 25 : 50
strikeStep = stepIn == "Auto" ? autoStep : int(str.tonumber(stepIn))

// ============================================================
// 2. LEG 1
// ============================================================
g1 = "2. Leg 1"
l1On    = input.bool(true, "On", inline="L1a", group=g1)
l1CP    = input.string("CE", "", options=["CE", "PE"], inline="L1a", group=g1)
l1Side  = input.string("Buy", "", options=["Buy", "Sell"], inline="L1a", group=g1)
l1YM    = input.string("2026-12", "Expiry", options=["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03", "2027-04", "2027-05", "2027-06", "2027-07", "2027-08", "2027-09", "2027-10", "2027-11", "2027-12", "2028-01", "2028-02", "2028-03", "2028-04", "2028-05", "2028-06", "2028-07", "2028-08", "2028-09", "2028-10", "2028-11", "2028-12", "2029-01", "2029-02", "2029-03", "2029-04", "2029-05", "2029-06", "2029-07", "2029-08", "2029-09", "2029-10", "2029-11", "2029-12", "2030-01", "2030-02", "2030-03", "2030-04", "2030-05", "2030-06", "2030-07", "2030-08", "2030-09", "2030-10", "2030-11", "2030-12"], inline="L1d", group=g1)
l1DD    = input.string("29", "", options=["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "30", "31"], inline="L1d", group=g1)
l1K     = input.string("25000", "Strike", options=["0", "1000", "2000", "3000", "4000", "5000", "6000", "7000", "8000", "9000", "10000", "11000", "12000", "13000", "14000", "15000", "16000", "17000", "18000", "19000", "20000", "21000", "22000", "23000", "24000", "25000", "26000", "27000", "28000", "29000", "30000", "31000", "32000", "33000", "34000", "35000", "36000", "37000", "38000", "39000", "40000", "41000", "42000", "43000", "44000", "45000", "46000", "47000", "48000", "49000", "50000", "51000", "52000", "53000", "54000", "55000", "56000", "57000", "58000", "59000", "60000", "61000", "62000", "63000", "64000", "65000", "66000", "67000", "68000", "69000", "70000", "71000", "72000", "73000", "74000", "75000", "76000", "77000", "78000", "79000", "80000", "81000", "82000", "83000", "84000", "85000", "86000", "87000", "88000", "89000", "90000", "91000", "92000", "93000", "94000", "95000", "96000", "97000", "98000", "99000"], inline="L1b", group=g1)
l1KA    = input.string("0", "+", options=["0", "50", "100", "150", "200", "250", "300", "350", "400", "450", "500", "550", "600", "650", "700", "750", "800", "850", "900", "950"], inline="L1b", group=g1)
l1Lots  = input.int(1, "Lots", minval=0, inline="L1c", group=g1)
l1Entry = input.float(0.0, "Entry", minval=0, inline="L1c", group=g1)
l1Pick  = input.string("", "Symbol", group=g1, tooltip="Used only when Source = Symbol. Paste the exact ticker, e.g. NSE:NIFTY261229C25000.\n\nLeft empty on purpose: a text input is drawn as wide as its default value, and a 21 character ticker made this the widest row in the dialog, which pushed the OK button off screen on phones.")

// ============================================================
// 3. LEG 2
// ============================================================
g2 = "3. Leg 2"
l2On    = input.bool(true, "On", inline="L2a", group=g2)
l2CP    = input.string("PE", "", options=["CE", "PE"], inline="L2a", group=g2)
l2Side  = input.string("Buy", "", options=["Buy", "Sell"], inline="L2a", group=g2)
l2YM    = input.string("2026-12", "Expiry", options=["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03", "2027-04", "2027-05", "2027-06", "2027-07", "2027-08", "2027-09", "2027-10", "2027-11", "2027-12", "2028-01", "2028-02", "2028-03", "2028-04", "2028-05", "2028-06", "2028-07", "2028-08", "2028-09", "2028-10", "2028-11", "2028-12", "2029-01", "2029-02", "2029-03", "2029-04", "2029-05", "2029-06", "2029-07", "2029-08", "2029-09", "2029-10", "2029-11", "2029-12", "2030-01", "2030-02", "2030-03", "2030-04", "2030-05", "2030-06", "2030-07", "2030-08", "2030-09", "2030-10", "2030-11", "2030-12"], inline="L2d", group=g2)
l2DD    = input.string("29", "", options=["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "30", "31"], inline="L2d", group=g2)
l2K     = input.string("25000", "Strike", options=["0", "1000", "2000", "3000", "4000", "5000", "6000", "7000", "8000", "9000", "10000", "11000", "12000", "13000", "14000", "15000", "16000", "17000", "18000", "19000", "20000", "21000", "22000", "23000", "24000", "25000", "26000", "27000", "28000", "29000", "30000", "31000", "32000", "33000", "34000", "35000", "36000", "37000", "38000", "39000", "40000", "41000", "42000", "43000", "44000", "45000", "46000", "47000", "48000", "49000", "50000", "51000", "52000", "53000", "54000", "55000", "56000", "57000", "58000", "59000", "60000", "61000", "62000", "63000", "64000", "65000", "66000", "67000", "68000", "69000", "70000", "71000", "72000", "73000", "74000", "75000", "76000", "77000", "78000", "79000", "80000", "81000", "82000", "83000", "84000", "85000", "86000", "87000", "88000", "89000", "90000", "91000", "92000", "93000", "94000", "95000", "96000", "97000", "98000", "99000"], inline="L2b", group=g2)
l2KA    = input.string("0", "+", options=["0", "50", "100", "150", "200", "250", "300", "350", "400", "450", "500", "550", "600", "650", "700", "750", "800", "850", "900", "950"], inline="L2b", group=g2)
l2Lots  = input.int(1, "Lots", minval=0, inline="L2c", group=g2)
l2Entry = input.float(0.0, "Entry", minval=0, inline="L2c", group=g2)
l2Pick  = input.string("", "Symbol", group=g2, tooltip="Used only when Source = Symbol. Paste the exact ticker, e.g. NSE:NIFTY261229C25000.\n\nLeft empty on purpose: a text input is drawn as wide as its default value, and a 21 character ticker made this the widest row in the dialog, which pushed the OK button off screen on phones.")

// ============================================================
// 4. LEG 3
// ============================================================
g3 = "4. Leg 3"
l3On    = input.bool(false, "On", inline="L3a", group=g3)
l3CP    = input.string("CE", "", options=["CE", "PE"], inline="L3a", group=g3)
l3Side  = input.string("Sell", "", options=["Buy", "Sell"], inline="L3a", group=g3)
l3YM    = input.string("2026-12", "Expiry", options=["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03", "2027-04", "2027-05", "2027-06", "2027-07", "2027-08", "2027-09", "2027-10", "2027-11", "2027-12", "2028-01", "2028-02", "2028-03", "2028-04", "2028-05", "2028-06", "2028-07", "2028-08", "2028-09", "2028-10", "2028-11", "2028-12", "2029-01", "2029-02", "2029-03", "2029-04", "2029-05", "2029-06", "2029-07", "2029-08", "2029-09", "2029-10", "2029-11", "2029-12", "2030-01", "2030-02", "2030-03", "2030-04", "2030-05", "2030-06", "2030-07", "2030-08", "2030-09", "2030-10", "2030-11", "2030-12"], inline="L3d", group=g3)
l3DD    = input.string("29", "", options=["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "30", "31"], inline="L3d", group=g3)
l3K     = input.string("25000", "Strike", options=["0", "1000", "2000", "3000", "4000", "5000", "6000", "7000", "8000", "9000", "10000", "11000", "12000", "13000", "14000", "15000", "16000", "17000", "18000", "19000", "20000", "21000", "22000", "23000", "24000", "25000", "26000", "27000", "28000", "29000", "30000", "31000", "32000", "33000", "34000", "35000", "36000", "37000", "38000", "39000", "40000", "41000", "42000", "43000", "44000", "45000", "46000", "47000", "48000", "49000", "50000", "51000", "52000", "53000", "54000", "55000", "56000", "57000", "58000", "59000", "60000", "61000", "62000", "63000", "64000", "65000", "66000", "67000", "68000", "69000", "70000", "71000", "72000", "73000", "74000", "75000", "76000", "77000", "78000", "79000", "80000", "81000", "82000", "83000", "84000", "85000", "86000", "87000", "88000", "89000", "90000", "91000", "92000", "93000", "94000", "95000", "96000", "97000", "98000", "99000"], inline="L3b", group=g3)
l3KA    = input.string("500", "+", options=["0", "50", "100", "150", "200", "250", "300", "350", "400", "450", "500", "550", "600", "650", "700", "750", "800", "850", "900", "950"], inline="L3b", group=g3)
l3Lots  = input.int(1, "Lots", minval=0, inline="L3c", group=g3)
l3Entry = input.float(0.0, "Entry", minval=0, inline="L3c", group=g3)
l3Pick  = input.string("", "Symbol", group=g3, tooltip="Used only when Source = Symbol. Paste the exact ticker, e.g. NSE:NIFTY261229C25000.\n\nLeft empty on purpose: a text input is drawn as wide as its default value, and a 21 character ticker made this the widest row in the dialog, which pushed the OK button off screen on phones.")

// ============================================================
// 5. LEG 4
// ============================================================
g4 = "5. Leg 4"
l4On    = input.bool(false, "On", inline="L4a", group=g4)
l4CP    = input.string("PE", "", options=["CE", "PE"], inline="L4a", group=g4)
l4Side  = input.string("Sell", "", options=["Buy", "Sell"], inline="L4a", group=g4)
l4YM    = input.string("2026-12", "Expiry", options=["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03", "2027-04", "2027-05", "2027-06", "2027-07", "2027-08", "2027-09", "2027-10", "2027-11", "2027-12", "2028-01", "2028-02", "2028-03", "2028-04", "2028-05", "2028-06", "2028-07", "2028-08", "2028-09", "2028-10", "2028-11", "2028-12", "2029-01", "2029-02", "2029-03", "2029-04", "2029-05", "2029-06", "2029-07", "2029-08", "2029-09", "2029-10", "2029-11", "2029-12", "2030-01", "2030-02", "2030-03", "2030-04", "2030-05", "2030-06", "2030-07", "2030-08", "2030-09", "2030-10", "2030-11", "2030-12"], inline="L4d", group=g4)
l4DD    = input.string("29", "", options=["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "30", "31"], inline="L4d", group=g4)
l4K     = input.string("24000", "Strike", options=["0", "1000", "2000", "3000", "4000", "5000", "6000", "7000", "8000", "9000", "10000", "11000", "12000", "13000", "14000", "15000", "16000", "17000", "18000", "19000", "20000", "21000", "22000", "23000", "24000", "25000", "26000", "27000", "28000", "29000", "30000", "31000", "32000", "33000", "34000", "35000", "36000", "37000", "38000", "39000", "40000", "41000", "42000", "43000", "44000", "45000", "46000", "47000", "48000", "49000", "50000", "51000", "52000", "53000", "54000", "55000", "56000", "57000", "58000", "59000", "60000", "61000", "62000", "63000", "64000", "65000", "66000", "67000", "68000", "69000", "70000", "71000", "72000", "73000", "74000", "75000", "76000", "77000", "78000", "79000", "80000", "81000", "82000", "83000", "84000", "85000", "86000", "87000", "88000", "89000", "90000", "91000", "92000", "93000", "94000", "95000", "96000", "97000", "98000", "99000"], inline="L4b", group=g4)
l4KA    = input.string("500", "+", options=["0", "50", "100", "150", "200", "250", "300", "350", "400", "450", "500", "550", "600", "650", "700", "750", "800", "850", "900", "950"], inline="L4b", group=g4)
l4Lots  = input.int(1, "Lots", minval=0, inline="L4c", group=g4)
l4Entry = input.float(0.0, "Entry", minval=0, inline="L4c", group=g4)
l4Pick  = input.string("", "Symbol", group=g4, tooltip="Used only when Source = Symbol. Paste the exact ticker, e.g. NSE:NIFTY261229C25000.\n\nLeft empty on purpose: a text input is drawn as wide as its default value, and a 21 character ticker made this the widest row in the dialog, which pushed the OK button off screen on phones.")

// ============================================================
// 6. COMBO CHART LAYOUT
// ============================================================
grpCombo = "6. Combo Chart"
showCombo   = input.bool(true, "Show", inline="cb1", group=grpCombo)
comboStyle  = input.string("Candles", "", options=["Candles", "Line"], inline="cb1", group=grpCombo)
comboWidth  = input.int(2, "Width", minval=1, maxval=4, inline="cb2", group=grpCombo)
comboLineCol = input.color(color.yellow, "", inline="cb2", group=grpCombo)
comboUpCol  = input.color(color.new(color.green, 0), "Up / Dn", inline="cb3", group=grpCombo)
comboDnCol  = input.color(color.new(color.red, 0), "", inline="cb3", group=grpCombo)
showPriceLine = input.bool(false, "Extra close line", group=grpCombo)
rangeMode = input.string("Spot linked", "Bar range", options=["Spot linked", "Body only", "Sum leg wicks"], group=grpCombo, tooltip="A combo's open and close are exact, but its high and low have to be inferred from the legs.\n\nSpot linked (recommended) = values the combo with the underlying at its bar high and again at its bar low. Every call is at its high while every put is at its low, which is what actually happens. Gives normal wicks.\n\nBody only = no wicks at all.\n\nSum leg wicks = old behaviour. Adds up each leg's own extreme as if they all peaked on the same tick, so wicks come out far too long on straddles and strangles.")

// ============================================================
// 7. CALL CHART LAYOUT
// ============================================================
grpCall = "7. Call Chart"
showCall   = input.bool(true, "Show", inline="ca1", group=grpCall)
callStyle  = input.string("Line", "", options=["Candles", "Line"], inline="ca1", group=grpCall)
callWidth  = input.int(2, "Width", minval=1, maxval=4, inline="ca2", group=grpCall)
callLineCol = input.color(color.aqua, "", inline="ca2", group=grpCall)
callUpCol  = input.color(color.new(color.teal, 0), "Up / Dn", inline="ca3", group=grpCall)
callDnCol  = input.color(color.new(color.maroon, 0), "", inline="ca3", group=grpCall)

// ============================================================
// 8. PUT CHART LAYOUT
// ============================================================
grpPut = "8. Put Chart"
showPut   = input.bool(true, "Show", inline="pu1", group=grpPut)
putStyle  = input.string("Line", "", options=["Candles", "Line"], inline="pu1", group=grpPut)
putWidth  = input.int(2, "Width", minval=1, maxval=4, inline="pu2", group=grpPut)
putLineCol = input.color(color.fuchsia, "", inline="pu2", group=grpPut)
putUpCol  = input.color(color.new(color.purple, 0), "Up / Dn", inline="pu3", group=grpPut)
putDnCol  = input.color(color.new(color.orange, 0), "", inline="pu3", group=grpPut)

legPriceMode = input.string("Absolute", "Call/Put price", options=["Absolute", "Net (signed)"], group=grpPut, tooltip="Absolute = always positive (spread cost).\nNet = keeps the sign of the position (credit shows negative).")

// ============================================================
// 9. CALL/PUT SCALING
// Pine cannot pin one plot to the left scale, so instead the call and put
// series can be mapped into the combo price band to remove the visual gap.
// The table always shows the real un-scaled prices.
// ============================================================
grpScale = "9. Call/Put Scaling"
scaleMode = input.string("Auto fit", "Mode", options=["Raw", "Auto fit", "Manual"], group=grpScale, tooltip="Raw     = true prices (big gap if combo is a spread).\nAuto fit = follows the combo price band automatically.\nManual   = fixed multiplier + offset, keeps the shape exactly.\n\nFor real left/right scales add this indicator twice: one copy with only the combo on (pin Right), one with only call/put on (pin Left).")
fitSmooth = input.int(200, "Fit smoothing", minval=1, maxval=5000, group=grpScale, tooltip="Bars of smoothing on the auto fit factor. Higher = steadier, lower = tracks the combo faster.")
manMult   = input.float(1.0, "Multiply", minval=0.0001, step=0.1, inline="s1", group=grpScale)
manOffs   = input.float(0.0, "Offset", step=1, inline="s1", group=grpScale)

// ============================================================
// 10. VWAP / EMA / SUPERTREND
// ============================================================
grpInd = "10. Indicators"
showVwap = input.bool(true, "VWAP", inline="i1", group=grpInd)
vwapCol  = input.color(color.orange, "", inline="i1", group=grpInd)
showEma1 = input.bool(true, "EMA 1", inline="i2", group=grpInd)
ema1Len  = input.int(9, "", minval=1, inline="i2", group=grpInd)
showEma2 = input.bool(true, "EMA 2", inline="i3", group=grpInd)
ema2Len  = input.int(21, "", minval=1, inline="i3", group=grpInd)
ema1Col  = input.color(color.aqua, "EMA colors", inline="i3b", group=grpInd)
ema2Col  = input.color(color.fuchsia, "", inline="i3b", group=grpInd)
showSt   = input.bool(true, "Supertrend", inline="i4", group=grpInd)
stFactor = input.float(3.0, "F", minval=0.1, step=0.1, inline="i4", group=grpInd)
stAtrLen = input.int(10, "ST ATR", minval=1, group=grpInd)
stUpCol  = input.color(color.green, "ST colors", inline="i5", group=grpInd)
stDnCol  = input.color(color.red, "", inline="i5", group=grpInd)

// ============================================================
// 11. TABLE
// ============================================================
grpTbl = "11. Table"
showTbl     = input.bool(true, "Show table", group=grpTbl)
tblSizeIn   = input.string("Tiny", "Text size", options=["Tiny", "Small", "Normal", "Large", "Huge"], group=grpTbl)
tblPosIn    = input.string("Top Right", "Position", options=["Top Left", "Top Center", "Top Right", "Middle Left", "Middle Center", "Middle Right", "Bottom Left", "Bottom Center", "Bottom Right"], group=grpTbl)
showLegRows = input.bool(true, "Show leg rows", group=grpTbl, tooltip="Turn off for a compact 4-row table on small screens.")
plUnit      = input.string("Points", "P/L unit", options=["Points", "Rupees"], group=grpTbl, tooltip="Rupees multiplies by the instrument lot size.")
tblBgCol    = input.color(color.new(color.black, 70), "Background", inline="t1", group=grpTbl)
tblTxtCol   = input.color(color.white, "Text", inline="t1", group=grpTbl)
showSyms    = input.bool(true, "Symbol check", group=grpTbl, tooltip="Lists the exact option symbol each leg requested and whether data came back. Leave this on while setting the legs up: NO DATA means that strike/expiry combination does not exist.")
symPosIn    = input.string("Bottom Left", "Check at", options=["Top Left", "Top Center", "Top Right", "Middle Left", "Middle Center", "Middle Right", "Bottom Left", "Bottom Center", "Bottom Right"], group=grpTbl)

tblSize = f_textSize(tblSizeIn)

// ============================================================
// BUILD LEG SYMBOLS
// ============================================================
// Expiry per leg. Legs 2-4 fall back to Leg 1 when "same expiry" is on,
// which is what a plain straddle / strangle needs. Turn it off for calendars.
e1YM = l1YM
e1DD = l1DD
e2YM = sameExp ? l1YM : l2YM
e2DD = sameExp ? l1DD : l2DD
e3YM = sameExp ? l1YM : l3YM
e3DD = sameExp ? l1DD : l3DD
e4YM = sameExp ? l1YM : l4YM
e4DD = sameExp ? l1DD : l4DD

// Expiry dropdown holds YYYY-MM in one control to keep the mobile form narrow.
e1YY = str.substring(e1YM, 2, 4)
e1MM = str.substring(e1YM, 5, 7)
e2YY = str.substring(e2YM, 2, 4)
e2MM = str.substring(e2YM, 5, 7)
e3YY = str.substring(e3YM, 2, 4)
e3MM = str.substring(e3YM, 5, 7)
e4YY = str.substring(e4YM, 2, 4)
e4MM = str.substring(e4YM, 5, 7)

// Strike = base dropdown + increment dropdown, snapped to the index step.
// Written inline (no helper function) so the result keeps the "simple"
// qualifier that request.security() wants for its symbol argument.
// float() on the divisor matters: int / int truncates in Pine v5.
l1Strike = int(math.round((int(str.tonumber(l1K)) + int(str.tonumber(l1KA))) / float(strikeStep)) * strikeStep)
l2Strike = int(math.round((int(str.tonumber(l2K)) + int(str.tonumber(l2KA))) / float(strikeStep)) * strikeStep)
l3Strike = int(math.round((int(str.tonumber(l3K)) + int(str.tonumber(l3KA))) / float(strikeStep)) * strikeStep)
l4Strike = int(math.round((int(str.tonumber(l4K)) + int(str.tonumber(l4KA))) / float(strikeStep)) * strikeStep)

// Month code, only used by the Old symbol format
m1Txt = e1MM == "01" ? "JAN" : e1MM == "02" ? "FEB" : e1MM == "03" ? "MAR" : e1MM == "04" ? "APR" : e1MM == "05" ? "MAY" : e1MM == "06" ? "JUN" : e1MM == "07" ? "JUL" : e1MM == "08" ? "AUG" : e1MM == "09" ? "SEP" : e1MM == "10" ? "OCT" : e1MM == "11" ? "NOV" : "DEC"
m2Txt = e2MM == "01" ? "JAN" : e2MM == "02" ? "FEB" : e2MM == "03" ? "MAR" : e2MM == "04" ? "APR" : e2MM == "05" ? "MAY" : e2MM == "06" ? "JUN" : e2MM == "07" ? "JUL" : e2MM == "08" ? "AUG" : e2MM == "09" ? "SEP" : e2MM == "10" ? "OCT" : e2MM == "11" ? "NOV" : "DEC"
m3Txt = e3MM == "01" ? "JAN" : e3MM == "02" ? "FEB" : e3MM == "03" ? "MAR" : e3MM == "04" ? "APR" : e3MM == "05" ? "MAY" : e3MM == "06" ? "JUN" : e3MM == "07" ? "JUL" : e3MM == "08" ? "AUG" : e3MM == "09" ? "SEP" : e3MM == "10" ? "OCT" : e3MM == "11" ? "NOV" : "DEC"
m4Txt = e4MM == "01" ? "JAN" : e4MM == "02" ? "FEB" : e4MM == "03" ? "MAR" : e4MM == "04" ? "APR" : e4MM == "05" ? "MAY" : e4MM == "06" ? "JUN" : e4MM == "07" ? "JUL" : e4MM == "08" ? "AUG" : e4MM == "09" ? "SEP" : e4MM == "10" ? "OCT" : e4MM == "11" ? "NOV" : "DEC"

// Verified live format: NSE:NIFTY260908C24200  (root + YYMMDD + C/P + strike)
l1Built = symFmt == "New" ? exch + ":" + rootFinal + e1YY + e1MM + e1DD + (l1CP == "CE" ? "C" : "P") + str.tostring(l1Strike) : exch + ":" + rootFinal + e1DD + m1Txt + e1YY + str.tostring(l1Strike) + l1CP
l2Built = symFmt == "New" ? exch + ":" + rootFinal + e2YY + e2MM + e2DD + (l2CP == "CE" ? "C" : "P") + str.tostring(l2Strike) : exch + ":" + rootFinal + e2DD + m2Txt + e2YY + str.tostring(l2Strike) + l2CP
l3Built = symFmt == "New" ? exch + ":" + rootFinal + e3YY + e3MM + e3DD + (l3CP == "CE" ? "C" : "P") + str.tostring(l3Strike) : exch + ":" + rootFinal + e3DD + m3Txt + e3YY + str.tostring(l3Strike) + l3CP
l4Built = symFmt == "New" ? exch + ":" + rootFinal + e4YY + e4MM + e4DD + (l4CP == "CE" ? "C" : "P") + str.tostring(l4Strike) : exch + ":" + rootFinal + e4DD + m4Txt + e4YY + str.tostring(l4Strike) + l4CP

usePicker = symMode == "Symbol"
// An empty Symbol field would make request.security() fall back to the chart's
// own symbol and quietly feed the index price in as a premium. Substitute a
// deliberately invalid ticker so the leg resolves to na and reads NO DATA.
l1Sym = usePicker ? (l1Pick == "" ? "NONE:NONE" : l1Pick) : l1Built
l2Sym = usePicker ? (l2Pick == "" ? "NONE:NONE" : l2Pick) : l2Built
l3Sym = usePicker ? (l3Pick == "" ? "NONE:NONE" : l3Pick) : l3Built
l4Sym = usePicker ? (l4Pick == "" ? "NONE:NONE" : l4Pick) : l4Built

// Strike / type shown in the table
[p1K, p1T] = f_parseOptionInfo(l1Sym)
[p2K, p2T] = f_parseOptionInfo(l2Sym)
[p3K, p3T] = f_parseOptionInfo(l3Sym)
[p4K, p4T] = f_parseOptionInfo(l4Sym)

l1KShow = usePicker ? p1K : float(l1Strike)
l2KShow = usePicker ? p2K : float(l2Strike)
l3KShow = usePicker ? p3K : float(l3Strike)
l4KShow = usePicker ? p4K : float(l4Strike)

l1IsCall = usePicker ? p1T == "Call" : l1CP == "CE"
l2IsCall = usePicker ? p2T == "Call" : l2CP == "CE"
l3IsCall = usePicker ? p3T == "Call" : l3CP == "CE"
l4IsCall = usePicker ? p4T == "Call" : l4CP == "CE"

// In calendar mode each leg has its own expiry, so tag the C/P cell with the
// leg's expiry (DD/MM). With one shared expiry the tag is left off.
showExpTag = (not usePicker) and (not sameExp)
l1TShow = (usePicker ? p1T : (l1CP == "CE" ? "Call" : "Put")) + (showExpTag ? " " + e1DD + "/" + e1MM : "")
l2TShow = (usePicker ? p2T : (l2CP == "CE" ? "Call" : "Put")) + (showExpTag ? " " + e2DD + "/" + e2MM : "")
l3TShow = (usePicker ? p3T : (l3CP == "CE" ? "Call" : "Put")) + (showExpTag ? " " + e3DD + "/" + e3MM : "")
l4TShow = (usePicker ? p4T : (l4CP == "CE" ? "Call" : "Put")) + (showExpTag ? " " + e4DD + "/" + e4MM : "")

// ============================================================
// FETCH OHLCV (invalid symbols return na instead of erroring)
// ============================================================
// These are called directly at global scope on purpose. Wrapping
// request.security() in a user-defined function makes Pine v5 hoist the call
// and demand a "simple string" symbol, which breaks a symbol built from
// dropdowns. Called inline like this, dynamic_requests=true applies properly.
[o1, h1, lo1, c1, v1d] = request.security(l1Sym, timeframe.period, [open, high, low, close, volume], lookahead=barmerge.lookahead_off, ignore_invalid_symbol=true)
[o2, h2, lo2, c2, v2d] = request.security(l2Sym, timeframe.period, [open, high, low, close, volume], lookahead=barmerge.lookahead_off, ignore_invalid_symbol=true)
[o3, h3, lo3, c3, v3d] = request.security(l3Sym, timeframe.period, [open, high, low, close, volume], lookahead=barmerge.lookahead_off, ignore_invalid_symbol=true)
[o4, h4, lo4, c4, v4d] = request.security(l4Sym, timeframe.period, [open, high, low, close, volume], lookahead=barmerge.lookahead_off, ignore_invalid_symbol=true)

// ============================================================
// SIDE / QTY / VALIDITY
// ============================================================
s1 = l1Side == "Buy" ? 1 : -1
s2 = l2Side == "Buy" ? 1 : -1
s3 = l3Side == "Buy" ? 1 : -1
s4 = l4Side == "Buy" ? 1 : -1

q1 = l1On ? l1Lots : 0
q2 = l2On ? l2Lots : 0
q3 = l3On ? l3Lots : 0
q4 = l4On ? l4Lots : 0

// A leg only counts when it is enabled, has lots, and actually returned data.
ok1 = l1On and l1Lots > 0 and not na(c1)
ok2 = l2On and l2Lots > 0 and not na(c2)
ok3 = l3On and l3Lots > 0 and not na(c3)
ok4 = l4On and l4Lots > 0 and not na(c4)

activeCount = (ok1 ? 1 : 0) + (ok2 ? 1 : 0) + (ok3 ? 1 : 0) + (ok4 ? 1 : 0)

// ============================================================
// PICK THE FIRST TWO ACTIVE LEGS (for the 1 / 2 leg logic)
// ============================================================
float x1O = na
float x1H = na
float x1L = na
float x1C = na
int   x1S = na

float x2O = na
float x2H = na
float x2L = na
float x2C = na
int   x2S = na

int slotN = 0

if ok1
    slotN += 1
    if slotN == 1
        x1O := q1 * o1
        x1H := q1 * h1
        x1L := q1 * lo1
        x1C := q1 * c1
        x1S := s1
    else if slotN == 2
        x2O := q1 * o1
        x2H := q1 * h1
        x2L := q1 * lo1
        x2C := q1 * c1
        x2S := s1

if ok2
    slotN += 1
    if slotN == 1
        x1O := q2 * o2
        x1H := q2 * h2
        x1L := q2 * lo2
        x1C := q2 * c2
        x1S := s2
    else if slotN == 2
        x2O := q2 * o2
        x2H := q2 * h2
        x2L := q2 * lo2
        x2C := q2 * c2
        x2S := s2

if ok3
    slotN += 1
    if slotN == 1
        x1O := q3 * o3
        x1H := q3 * h3
        x1L := q3 * lo3
        x1C := q3 * c3
        x1S := s3
    else if slotN == 2
        x2O := q3 * o3
        x2H := q3 * h3
        x2L := q3 * lo3
        x2C := q3 * c3
        x2S := s3

if ok4
    slotN += 1
    if slotN == 1
        x1O := q4 * o4
        x1H := q4 * h4
        x1L := q4 * lo4
        x1C := q4 * c4
        x1S := s4
    else if slotN == 2
        x2O := q4 * o4
        x2H := q4 * h4
        x2L := q4 * lo4
        x2C := q4 * c4
        x2S := s4

// 2 legs: opposite sides -> difference, same side -> sum
isOpposite = activeCount == 2 and not na(x1S) and not na(x2S) and x1S != x2S

specialOpen  = isOpposite ? math.abs(x1O - x2O) : x1O + x2O
specialHigh  = isOpposite ? math.max(math.abs(x1H - x2L), math.abs(x2H - x1L)) : x1H + x2H
specialLow   = isOpposite ? math.min(math.abs(x1L - x2H), math.abs(x2L - x1H)) : x1L + x2L
specialClose = isOpposite ? math.abs(x1C - x2C) : x1C + x2C

specialHighFix = math.max(specialHigh, math.max(specialOpen, specialClose))
specialLowFix  = math.min(specialLow, math.min(specialOpen, specialClose))

// ============================================================
// SIGNED NET COMBO (3 / 4 legs, and used for totals)
// ============================================================
normalOpen  = f_w(ok1, s1, q1, o1) + f_w(ok2, s2, q2, o2) + f_w(ok3, s3, q3, o3) + f_w(ok4, s4, q4, o4)
normalClose = f_w(ok1, s1, q1, c1) + f_w(ok2, s2, q2, c2) + f_w(ok3, s3, q3, c3) + f_w(ok4, s4, q4, c4)
normalRawHi = f_wHigh(ok1, s1, q1, h1, lo1) + f_wHigh(ok2, s2, q2, h2, lo2) + f_wHigh(ok3, s3, q3, h3, lo3) + f_wHigh(ok4, s4, q4, h4, lo4)
normalRawLo = f_wLow(ok1, s1, q1, h1, lo1)  + f_wLow(ok2, s2, q2, h2, lo2)  + f_wLow(ok3, s3, q3, h3, lo3)  + f_wLow(ok4, s4, q4, h4, lo4)

normalHigh = math.max(normalRawHi, math.max(normalOpen, normalClose))
normalLow  = math.min(normalRawLo, math.min(normalOpen, normalClose))

comboOpen  = activeCount == 0 ? na : activeCount == 1 ? x1O : activeCount == 2 ? specialOpen : normalOpen
comboClose = activeCount == 0 ? na : activeCount == 1 ? x1C : activeCount == 2 ? specialClose : normalClose

comboSumHi = activeCount == 0 ? na : activeCount == 1 ? x1H : activeCount == 2 ? specialHighFix : normalHigh
comboSumLo = activeCount == 0 ? na : activeCount == 1 ? x1L : activeCount == 2 ? specialLowFix : normalLow

// ---- Spot-linked range ----
// Value the whole combo twice: once with the underlying at its bar high and
// once at its bar low. The true high and low sit at those two points.
netAtSpotHi = f_atSpotHi(ok1, s1, q1, l1IsCall, h1, lo1) + f_atSpotHi(ok2, s2, q2, l2IsCall, h2, lo2) + f_atSpotHi(ok3, s3, q3, l3IsCall, h3, lo3) + f_atSpotHi(ok4, s4, q4, l4IsCall, h4, lo4)
netAtSpotLo = f_atSpotLo(ok1, s1, q1, l1IsCall, h1, lo1) + f_atSpotLo(ok2, s2, q2, l2IsCall, h2, lo2) + f_atSpotLo(ok3, s3, q3, l3IsCall, h3, lo3) + f_atSpotLo(ok4, s4, q4, l4IsCall, h4, lo4)

// 1 and 2 leg combos are displayed unsigned (see comboOpen above), so the two
// spot valuations get the same absolute treatment to stay on the same scale.
absCombo = activeCount <= 2
spotEndA = absCombo ? math.abs(netAtSpotHi) : netAtSpotHi
spotEndB = absCombo ? math.abs(netAtSpotLo) : netAtSpotLo

comboSpotHi = math.max(math.max(spotEndA, spotEndB), math.max(comboOpen, comboClose))
comboSpotLo = math.min(math.min(spotEndA, spotEndB), math.min(comboOpen, comboClose))

comboHigh = activeCount == 0 ? na : rangeMode == "Sum leg wicks" ? comboSumHi : rangeMode == "Body only" ? math.max(comboOpen, comboClose) : comboSpotHi
comboLow  = activeCount == 0 ? na : rangeMode == "Sum leg wicks" ? comboSumLo : rangeMode == "Body only" ? math.min(comboOpen, comboClose) : comboSpotLo

comboVolume = (ok1 and not na(v1d) ? v1d : 0) + (ok2 and not na(v2d) ? v2d : 0) + (ok3 and not na(v3d) ? v3d : 0) + (ok4 and not na(v4d) ? v4d : 0)

// ============================================================
// CALL-ONLY AND PUT-ONLY BASKETS
// ============================================================
cOk1 = ok1 and l1IsCall
cOk2 = ok2 and l2IsCall
cOk3 = ok3 and l3IsCall
cOk4 = ok4 and l4IsCall

pOk1 = ok1 and not l1IsCall
pOk2 = ok2 and not l2IsCall
pOk3 = ok3 and not l3IsCall
pOk4 = ok4 and not l4IsCall

callAny = cOk1 or cOk2 or cOk3 or cOk4
putAny  = pOk1 or pOk2 or pOk3 or pOk4

callNetO = f_w(cOk1, s1, q1, o1) + f_w(cOk2, s2, q2, o2) + f_w(cOk3, s3, q3, o3) + f_w(cOk4, s4, q4, o4)
callNetC = f_w(cOk1, s1, q1, c1) + f_w(cOk2, s2, q2, c2) + f_w(cOk3, s3, q3, c3) + f_w(cOk4, s4, q4, c4)
callNetH = f_wHigh(cOk1, s1, q1, h1, lo1) + f_wHigh(cOk2, s2, q2, h2, lo2) + f_wHigh(cOk3, s3, q3, h3, lo3) + f_wHigh(cOk4, s4, q4, h4, lo4)
callNetL = f_wLow(cOk1, s1, q1, h1, lo1)  + f_wLow(cOk2, s2, q2, h2, lo2)  + f_wLow(cOk3, s3, q3, h3, lo3)  + f_wLow(cOk4, s4, q4, h4, lo4)

putNetO = f_w(pOk1, s1, q1, o1) + f_w(pOk2, s2, q2, o2) + f_w(pOk3, s3, q3, o3) + f_w(pOk4, s4, q4, o4)
putNetC = f_w(pOk1, s1, q1, c1) + f_w(pOk2, s2, q2, c2) + f_w(pOk3, s3, q3, c3) + f_w(pOk4, s4, q4, c4)
putNetH = f_wHigh(pOk1, s1, q1, h1, lo1) + f_wHigh(pOk2, s2, q2, h2, lo2) + f_wHigh(pOk3, s3, q3, h3, lo3) + f_wHigh(pOk4, s4, q4, h4, lo4)
putNetL = f_wLow(pOk1, s1, q1, h1, lo1)  + f_wLow(pOk2, s2, q2, h2, lo2)  + f_wLow(pOk3, s3, q3, h3, lo3)  + f_wLow(pOk4, s4, q4, h4, lo4)

useAbs = legPriceMode == "Absolute"

// Spot-linked endpoints for a single-type basket: every leg in a call basket is
// at its high together, and at its low together (a put basket is the mirror,
// which the max/min below sorts out on its own).
callEndA = f_w(cOk1, s1, q1, h1) + f_w(cOk2, s2, q2, h2) + f_w(cOk3, s3, q3, h3) + f_w(cOk4, s4, q4, h4)
callEndB = f_w(cOk1, s1, q1, lo1) + f_w(cOk2, s2, q2, lo2) + f_w(cOk3, s3, q3, lo3) + f_w(cOk4, s4, q4, lo4)
putEndA  = f_w(pOk1, s1, q1, h1) + f_w(pOk2, s2, q2, h2) + f_w(pOk3, s3, q3, h3) + f_w(pOk4, s4, q4, h4)
putEndB  = f_w(pOk1, s1, q1, lo1) + f_w(pOk2, s2, q2, lo2) + f_w(pOk3, s3, q3, lo3) + f_w(pOk4, s4, q4, lo4)

callO0 = useAbs ? math.abs(callNetO) : callNetO
callC0 = useAbs ? math.abs(callNetC) : callNetC
callH0 = useAbs ? math.max(math.abs(callNetH), math.abs(callNetL)) : callNetH
callL0 = useAbs ? math.min(math.abs(callNetH), math.abs(callNetL)) : callNetL
callSA = useAbs ? math.abs(callEndA) : callEndA
callSB = useAbs ? math.abs(callEndB) : callEndB

callOpen  = callAny ? callO0 : na
callClose = callAny ? callC0 : na
callHigh  = not callAny ? na : rangeMode == "Sum leg wicks" ? math.max(callH0, math.max(callO0, callC0)) : rangeMode == "Body only" ? math.max(callO0, callC0) : math.max(math.max(callSA, callSB), math.max(callO0, callC0))
callLow   = not callAny ? na : rangeMode == "Sum leg wicks" ? math.min(callL0, math.min(callO0, callC0)) : rangeMode == "Body only" ? math.min(callO0, callC0) : math.min(math.min(callSA, callSB), math.min(callO0, callC0))

putO0 = useAbs ? math.abs(putNetO) : putNetO
putC0 = useAbs ? math.abs(putNetC) : putNetC
putH0 = useAbs ? math.max(math.abs(putNetH), math.abs(putNetL)) : putNetH
putL0 = useAbs ? math.min(math.abs(putNetH), math.abs(putNetL)) : putNetL
putSA = useAbs ? math.abs(putEndA) : putEndA
putSB = useAbs ? math.abs(putEndB) : putEndB

putOpen  = putAny ? putO0 : na
putClose = putAny ? putC0 : na
putHigh  = not putAny ? na : rangeMode == "Sum leg wicks" ? math.max(putH0, math.max(putO0, putC0)) : rangeMode == "Body only" ? math.max(putO0, putC0) : math.max(math.max(putSA, putSB), math.max(putO0, putC0))
putLow   = not putAny ? na : rangeMode == "Sum leg wicks" ? math.min(putL0, math.min(putO0, putC0)) : rangeMode == "Body only" ? math.min(putO0, putC0) : math.min(math.min(putSA, putSB), math.min(putO0, putC0))

// ============================================================
// CALL/PUT SCALING
// A single option premium sits far above a spread's net premium, so the
// call/put lines would otherwise be pushed to the top of the pane. The
// factor below maps them into the combo band. Call and put always share the
// same factor, so they stay comparable with each other.
// ============================================================
cpRef = na(callClose) ? putClose : na(putClose) ? callClose : (callClose + putClose) / 2

rawFactor = not na(comboClose) and not na(cpRef) and comboClose > 0 and cpRef > 0 ? comboClose / cpRef : na

var float fitFactor = na
fitFactor := na(rawFactor) ? nz(fitFactor[1], 1.0) : na(fitFactor[1]) ? rawFactor : fitFactor[1] + (rawFactor - fitFactor[1]) / fitSmooth

cpMult = scaleMode == "Auto fit" ? fitFactor : scaleMode == "Manual" ? manMult : 1.0
cpOffs = scaleMode == "Manual" ? manOffs : 0.0

f_scale(v, mult, offs) => na(v) ? na : v * mult + offs

callOpenP  = f_scale(callOpen, cpMult, cpOffs)
callHighP  = f_scale(callHigh, cpMult, cpOffs)
callLowP   = f_scale(callLow, cpMult, cpOffs)
callCloseP = f_scale(callClose, cpMult, cpOffs)

putOpenP  = f_scale(putOpen, cpMult, cpOffs)
putHighP  = f_scale(putHigh, cpMult, cpOffs)
putLowP   = f_scale(putLow, cpMult, cpOffs)
putCloseP = f_scale(putClose, cpMult, cpOffs)

// ============================================================
// PLOTS - COMBO (Candles or Line)
// ============================================================
comboCandleCol = comboClose >= comboOpen ? comboUpCol : comboDnCol
cbCandle = showCombo and comboStyle == "Candles"

plotcandle(cbCandle ? comboOpen : na, cbCandle ? comboHigh : na, cbCandle ? comboLow : na, cbCandle ? comboClose : na, title="Combo Candles", color=comboCandleCol, bordercolor=comboCandleCol, wickcolor=comboCandleCol)
plot(showCombo and comboStyle == "Line" ? comboClose : na, title="Combo Line", color=comboLineCol, linewidth=comboWidth)
plot(showPriceLine ? comboClose : na, title="Combo Close Line", color=comboLineCol, linewidth=1)

// ============================================================
// PLOTS - CALL BASKET (Candles or Line)
// ============================================================
callCandleCol = callClose >= callOpen ? callUpCol : callDnCol
caCandle = showCall and callStyle == "Candles"

plotcandle(caCandle ? callOpenP : na, caCandle ? callHighP : na, caCandle ? callLowP : na, caCandle ? callCloseP : na, title="Call Candles", color=callCandleCol, bordercolor=callCandleCol, wickcolor=callCandleCol)
plot(showCall and callStyle == "Line" ? callCloseP : na, title="Call Line", color=callLineCol, linewidth=callWidth)

// ============================================================
// PLOTS - PUT BASKET (Candles or Line)
// ============================================================
putCandleCol = putClose >= putOpen ? putUpCol : putDnCol
puCandle = showPut and putStyle == "Candles"

plotcandle(puCandle ? putOpenP : na, puCandle ? putHighP : na, puCandle ? putLowP : na, puCandle ? putCloseP : na, title="Put Candles", color=putCandleCol, bordercolor=putCandleCol, wickcolor=putCandleCol)
plot(showPut and putStyle == "Line" ? putCloseP : na, title="Put Line", color=putLineCol, linewidth=putWidth)

// ============================================================
// VWAP (session reset) on the combo price
// ============================================================
newSession = ta.change(time("D")) != 0
var float cumPV  = 0.0
var float cumVol = 0.0

if newSession
    cumPV := 0.0
    cumVol := 0.0

vwapSrc = (comboHigh + comboLow + comboClose) / 3
cumPV += nz(vwapSrc * comboVolume)
cumVol += nz(comboVolume)
vwapVal = cumVol != 0 ? cumPV / cumVol : na

plot(showVwap ? vwapVal : na, title="VWAP", color=vwapCol, linewidth=2)

// ============================================================
// EMAs
// ============================================================
ema1Val = ta.ema(comboClose, ema1Len)
ema2Val = ta.ema(comboClose, ema2Len)

plot(showEma1 ? ema1Val : na, title="EMA 1", color=ema1Col, linewidth=1)
plot(showEma2 ? ema2Val : na, title="EMA 2", color=ema2Col, linewidth=1)

// ============================================================
// SUPERTREND
// ============================================================
trueRange = math.max(comboHigh - comboLow, math.max(math.abs(comboHigh - nz(comboClose[1])), math.abs(comboLow - nz(comboClose[1]))))
atrVal = ta.rma(trueRange, stAtrLen)

stSrc = (comboHigh + comboLow) / 2
upBandBasic = stSrc + stFactor * atrVal
dnBandBasic = stSrc - stFactor * atrVal

var float upBand = na
var float dnBand = na
var int stDir = 1
var float stLine = na

upBand := na(upBand[1]) ? upBandBasic : (upBandBasic < upBand[1] or nz(comboClose[1]) > upBand[1] ? upBandBasic : upBand[1])
dnBand := na(dnBand[1]) ? dnBandBasic : (dnBandBasic > dnBand[1] or nz(comboClose[1]) < dnBand[1] ? dnBandBasic : dnBand[1])

stDir := na(stLine[1]) ? 1 : (stLine[1] == upBand[1] ? (comboClose > upBand ? -1 : 1) : (comboClose < dnBand ? 1 : -1))
stLine := stDir == -1 ? dnBand : upBand

plot(showSt ? stLine : na, title="Supertrend", color=stDir == -1 ? stUpCol : stDnCol, linewidth=2, style=plot.style_linebr)

// ============================================================
// P&L
// ============================================================
inRupees = plUnit == "Rupees"
m1 = inRupees ? f_getLotSize(l1Sym) : 1
m2 = inRupees ? f_getLotSize(l2Sym) : 1
m3 = inRupees ? f_getLotSize(l3Sym) : 1
m4 = inRupees ? f_getLotSize(l4Sym) : 1

e1 = ok1 and l1Entry > 0
e2 = ok2 and l2Entry > 0
e3 = ok3 and l3Entry > 0
e4 = ok4 and l4Entry > 0

pl1 = e1 ? s1 * (c1 - l1Entry) * l1Lots * m1 : na
pl2 = e2 ? s2 * (c2 - l2Entry) * l2Lots * m2 : na
pl3 = e3 ? s3 * (c3 - l3Entry) * l3Lots * m3 : na
pl4 = e4 ? s4 * (c4 - l4Entry) * l4Lots * m4 : na

anyEntry = e1 or e2 or e3 or e4

callEntryNet = (e1 and l1IsCall ? s1 * l1Entry * l1Lots * m1 : 0) + (e2 and l2IsCall ? s2 * l2Entry * l2Lots * m2 : 0) + (e3 and l3IsCall ? s3 * l3Entry * l3Lots * m3 : 0) + (e4 and l4IsCall ? s4 * l4Entry * l4Lots * m4 : 0)
putEntryNet  = (e1 and not l1IsCall ? s1 * l1Entry * l1Lots * m1 : 0) + (e2 and not l2IsCall ? s2 * l2Entry * l2Lots * m2 : 0) + (e3 and not l3IsCall ? s3 * l3Entry * l3Lots * m3 : 0) + (e4 and not l4IsCall ? s4 * l4Entry * l4Lots * m4 : 0)
totalEntryNet = callEntryNet + putEntryNet

callCurNet = f_w(cOk1, s1, q1 * m1, c1) + f_w(cOk2, s2, q2 * m2, c2) + f_w(cOk3, s3, q3 * m3, c3) + f_w(cOk4, s4, q4 * m4, c4)
putCurNet  = f_w(pOk1, s1, q1 * m1, c1) + f_w(pOk2, s2, q2 * m2, c2) + f_w(pOk3, s3, q3 * m3, c3) + f_w(pOk4, s4, q4 * m4, c4)
totalCurNet = callCurNet + putCurNet

callPL  = nz(pl1 * (l1IsCall ? 1 : 0)) + nz(pl2 * (l2IsCall ? 1 : 0)) + nz(pl3 * (l3IsCall ? 1 : 0)) + nz(pl4 * (l4IsCall ? 1 : 0))
putPL   = nz(pl1 * (l1IsCall ? 0 : 1)) + nz(pl2 * (l2IsCall ? 0 : 1)) + nz(pl3 * (l3IsCall ? 0 : 1)) + nz(pl4 * (l4IsCall ? 0 : 1))
totalPL = callPL + putPL

callHasEntry = (e1 and l1IsCall) or (e2 and l2IsCall) or (e3 and l3IsCall) or (e4 and l4IsCall)
putHasEntry  = (e1 and not l1IsCall) or (e2 and not l2IsCall) or (e3 and not l3IsCall) or (e4 and not l4IsCall)

callLotsNet = (cOk1 ? s1 * l1Lots : 0) + (cOk2 ? s2 * l2Lots : 0) + (cOk3 ? s3 * l3Lots : 0) + (cOk4 ? s4 * l4Lots : 0)
putLotsNet  = (pOk1 ? s1 * l1Lots : 0) + (pOk2 ? s2 * l2Lots : 0) + (pOk3 ? s3 * l3Lots : 0) + (pOk4 ? s4 * l4Lots : 0)

// ============================================================
// INFO TABLE
// Layout: Strike | C/P | Qty | Entry | LTP | P/L
// ============================================================
f_qtyTxt(ok, sgn, lots) => ok ? (sgn > 0 ? "+" : "-") + str.tostring(lots) : "-"
f_numTxt(ok, v) => ok and not na(v) ? str.tostring(v, "#.##") : "-"

f_fillRow(tbl, r, txtStrike, txtType, txtQty, txtEntry, txtLtp, plVal, plOk, ts, bg, tc) =>
    table.cell(tbl, 0, r, txtStrike, text_color=tc, bgcolor=bg, text_size=ts)
    table.cell(tbl, 1, r, txtType,   text_color=tc, bgcolor=bg, text_size=ts)
    table.cell(tbl, 2, r, txtQty,    text_color=tc, bgcolor=bg, text_size=ts)
    table.cell(tbl, 3, r, txtEntry,  text_color=tc, bgcolor=bg, text_size=ts)
    table.cell(tbl, 4, r, txtLtp,    text_color=tc, bgcolor=bg, text_size=ts)
    table.cell(tbl, 5, r, plOk ? str.tostring(plVal, "#.##") : "-", text_color=plOk ? (plVal >= 0 ? color.lime : color.red) : tc, bgcolor=bg, text_size=ts)

tblRows = showLegRows ? 8 : 4
rCall = showLegRows ? 5 : 1
rPut  = rCall + 1
rTot  = rPut + 1

var table infoTbl = table.new(f_tblPos(tblPosIn), 6, tblRows, bgcolor=tblBgCol, border_width=1)

if barstate.islast and showTbl
    hdrBg = color.new(color.blue, 40)
    table.cell(infoTbl, 0, 0, "Strike", text_color=color.white, bgcolor=hdrBg, text_size=tblSize)
    table.cell(infoTbl, 1, 0, "C/P",    text_color=color.white, bgcolor=hdrBg, text_size=tblSize)
    table.cell(infoTbl, 2, 0, "Qty",    text_color=color.white, bgcolor=hdrBg, text_size=tblSize)
    table.cell(infoTbl, 3, 0, "Entry",  text_color=color.white, bgcolor=hdrBg, text_size=tblSize)
    table.cell(infoTbl, 4, 0, "LTP",    text_color=color.white, bgcolor=hdrBg, text_size=tblSize)
    table.cell(infoTbl, 5, 0, "P/L",    text_color=color.white, bgcolor=hdrBg, text_size=tblSize)

    if showLegRows
        f_fillRow(infoTbl, 1, ok1 ? str.tostring(l1KShow, "#") : "-", ok1 ? l1TShow : "-", f_qtyTxt(ok1, s1, l1Lots), f_numTxt(e1, l1Entry), f_numTxt(ok1, c1), pl1, e1, tblSize, color.new(color.black, 100), tblTxtCol)
        f_fillRow(infoTbl, 2, ok2 ? str.tostring(l2KShow, "#") : "-", ok2 ? l2TShow : "-", f_qtyTxt(ok2, s2, l2Lots), f_numTxt(e2, l2Entry), f_numTxt(ok2, c2), pl2, e2, tblSize, color.new(color.black, 100), tblTxtCol)
        f_fillRow(infoTbl, 3, ok3 ? str.tostring(l3KShow, "#") : "-", ok3 ? l3TShow : "-", f_qtyTxt(ok3, s3, l3Lots), f_numTxt(e3, l3Entry), f_numTxt(ok3, c3), pl3, e3, tblSize, color.new(color.black, 100), tblTxtCol)
        f_fillRow(infoTbl, 4, ok4 ? str.tostring(l4KShow, "#") : "-", ok4 ? l4TShow : "-", f_qtyTxt(ok4, s4, l4Lots), f_numTxt(e4, l4Entry), f_numTxt(ok4, c4), pl4, e4, tblSize, color.new(color.black, 100), tblTxtCol)

    callBg = color.new(color.teal, 65)
    putBg  = color.new(color.purple, 65)
    totBg  = color.new(color.gray, 40)

    f_fillRow(infoTbl, rCall, "CALLS", "Call", callAny ? str.tostring(callLotsNet) : "-", f_numTxt(callHasEntry, callEntryNet), f_numTxt(callAny, callCurNet), callPL, callHasEntry, tblSize, callBg, color.white)
    f_fillRow(infoTbl, rPut,  "PUTS",  "Put",  putAny  ? str.tostring(putLotsNet)  : "-", f_numTxt(putHasEntry,  putEntryNet),  f_numTxt(putAny,  putCurNet),  putPL,  putHasEntry,  tblSize, putBg,  color.white)
    f_fillRow(infoTbl, rTot,  "TOTAL", plUnit == "Rupees" ? "Rs" : "Pts", str.tostring(activeCount) + "L", f_numTxt(anyEntry, totalEntryNet), f_numTxt(activeCount > 0, totalCurNet), totalPL, anyEntry, tblSize, totBg, color.white)

// ============================================================
// SYMBOL CHECK TABLE
// Shows the exact symbol each leg asked for. If a dropdown strike or expiry
// does not exist you will see "NO DATA" here instead of a blank chart.
// ============================================================
f_symRow(tbl, r, legName, sym, gotData, ts, tc) =>
    table.cell(tbl, 0, r, legName, text_color=tc, text_size=ts)
    table.cell(tbl, 1, r, sym, text_color=tc, text_size=ts)
    table.cell(tbl, 2, r, gotData ? "OK" : "NO DATA", text_color=gotData ? color.lime : color.red, text_size=ts)

var table symTbl = table.new(f_tblPos(symPosIn), 3, 5, bgcolor=tblBgCol, border_width=1)

if barstate.islast and showSyms
    symHdrBg = color.new(color.blue, 40)
    table.cell(symTbl, 0, 0, "Leg",    text_color=color.white, bgcolor=symHdrBg, text_size=tblSize)
    table.cell(symTbl, 1, 0, "Symbol", text_color=color.white, bgcolor=symHdrBg, text_size=tblSize)
    table.cell(symTbl, 2, 0, "Data",   text_color=color.white, bgcolor=symHdrBg, text_size=tblSize)

    f_symRow(symTbl, 1, l1On ? "1" : "1 off", l1Sym, not na(c1), tblSize, tblTxtCol)
    f_symRow(symTbl, 2, l2On ? "2" : "2 off", l2Sym, not na(c2), tblSize, tblTxtCol)
    f_symRow(symTbl, 3, l3On ? "3" : "3 off", l3Sym, not na(c3), tblSize, tblTxtCol)
    f_symRow(symTbl, 4, l4On ? "4" : "4 off", l4Sym, not na(c4), tblSize, tblTxtCol)
