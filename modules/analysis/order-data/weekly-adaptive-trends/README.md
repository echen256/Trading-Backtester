# Weekly adaptive-MACD strong trends — entered assets

This catalogue uses filled **BUY** orders from 2025 and 2026 as entries. It includes only trend periods containing at least one such entry date.

## Definition

- Start: first weekly close where adaptive MACD and its signal are both above zero.
- Confirmation: the first completed negative-histogram pullback after start keeps the signal strictly above zero; the confirmation date is its first non-negative histogram week.
- Strength: the trend sets a new high in the signal line versus all earlier available weekly history, and contains at least eight consecutive positive, increasing histogram weeks (the light-blue sequence).
- End: first week the signal reaches or falls below zero; otherwise the period remains active through the latest bar.

Scanned 236 entered underlyings; 138 had no daily archive rows. The signal ATH is relative to the downloaded history (2020-01-01 onward), not a vendor-guaranteed lifetime series. ‘Open through latest data’ means the available archive has no qualifying end signal, not that the trend is necessarily still live today.

## Qualifying periods

| Asset | Start | Confirmed | End | Signal ATH | Light-blue streak | Entry dates in period | Chart |
| --- | --- | --- | --- | --- | ---: | --- | --- |
| MRVL | 2025-08-15 | 2025-10-17 | open through latest data | 2026-06-16 (0.7538) | 14 | 2026-05-14 | [view](charts/MRVL.html) |
| HUT | 2025-08-01 | 2026-02-06 | 2026-03-20 | 2025-11-14 (0.6311) | 8 | 2025-10-02 | [view](charts/HUT.html) |

## Micro trends

A micro trend starts when either the adaptive MACD crosses above zero or 14-period RSI crosses above 50 (RSI−50 crosses zero), remains in force for at least three weekly bars, and expands 14-week ATR by at least 33% from the start. It ends on the first negative adaptive-MACD histogram week.

| Asset | Trigger | Start | Qualified | End | Max ATR expansion | Entry dates in period | Chart |
| --- | --- | --- | --- | --- | ---: | --- | --- |
| AMKR | MACD | 2026-05-15 | 2026-05-29 | 2026-07-10 | 40.5% | 2026-06-12, 2026-06-16, 2026-06-26 | [view](charts/AMKR.html) |
| MU | MACD | 2026-05-08 | 2026-05-22 | open through latest data | 59.2% | 2026-05-08, 2026-05-12, 2026-05-18, 2026-05-19, 2026-05-21, 2026-05-22, 2026-05-26, 2026-05-27, 2026-05-28, 2026-05-29, 2026-06-01, 2026-06-02, 2026-06-03, 2026-06-04, 2026-06-05, 2026-06-11, 2026-06-12, 2026-06-16 | [view](charts/MU.html) |
| QCOM | RSI-50 | 2026-04-24 | 2026-05-08 | open through latest data | 135.7% | 2026-04-24, 2026-04-30, 2026-05-06, 2026-05-08, 2026-05-12, 2026-05-14, 2026-05-15, 2026-05-20, 2026-05-21, 2026-05-26, 2026-05-28, 2026-05-29, 2026-06-01, 2026-06-05, 2026-06-09 | [view](charts/QCOM.html) |
| INTC | MACD | 2026-04-24 | 2026-05-08 | 2026-06-05 | 75.6% | 2026-04-24, 2026-04-29, 2026-05-05, 2026-05-15, 2026-05-19, 2026-05-20, 2026-05-27, 2026-05-28, 2026-06-03 | [view](charts/INTC.html) |
| CAR | MACD | 2026-04-17 | 2026-05-01 | 2026-05-22 | 109.6% | 2026-04-21, 2026-04-22, 2026-04-23, 2026-04-29 | [view](charts/CAR.html) |
| CIFR | RSI-50 | 2026-04-10 | 2026-04-24 | 2026-07-10 | 36.6% | 2026-05-13 | [view](charts/CIFR.html) |
| AMD | RSI-50 | 2026-04-02 | 2026-04-17 | 2026-07-02 | 122.9% | 2026-05-01, 2026-05-04, 2026-05-22 | [view](charts/AMD.html) |
| ARM | RSI-50 | 2026-03-20 | 2026-04-02 | 2026-07-10 | 226.0% | 2026-05-07, 2026-05-20, 2026-05-21 | [view](charts/ARM.html) |
| MRVL | RSI-50 | 2026-02-27 | 2026-03-13 | open through latest data | 242.2% | 2026-05-14 | [view](charts/MRVL.html) |
| NVTS | MACD | 2026-02-13 | 2026-02-27 | open through latest data | 127.1% | 2026-05-11, 2026-05-13, 2026-05-14, 2026-05-19, 2026-05-21, 2026-05-22, 2026-06-03 | [view](charts/NVTS.html) |
| NBIS | RSI-50 | 2026-02-13 | 2026-02-27 | open through latest data | 93.0% | 2026-05-28 | [view](charts/NBIS.html) |
| GLD | MACD | 2026-01-09 | 2026-01-23 | 2026-03-13 | 68.1% | 2026-01-09, 2026-01-14, 2026-01-21, 2026-01-23, 2026-02-02, 2026-02-03, 2026-02-09, 2026-02-19, 2026-02-27, 2026-03-05 | [view](charts/GLD.html) |
| GRAL | MACD | 2025-10-03 | 2025-10-17 | 2025-12-12 | 73.3% | 2025-11-20, 2025-11-21 | [view](charts/GRAL.html) |
| GLD | MACD | 2025-09-12 | 2025-09-26 | 2025-11-07 | 38.8% | 2025-09-12, 2025-09-15, 2025-09-17, 2025-09-22, 2025-09-23, 2025-09-25, 2025-10-13, 2025-10-20, 2025-10-23, 2025-10-29 | [view](charts/GLD.html) |
| SNDK | RSI-50 | 2025-08-22 | 2025-09-05 | 2025-12-05 | 439.9% | 2025-11-13, 2025-11-18, 2025-11-26, 2025-12-02, 2025-12-03 | [view](charts/SNDK.html) |
| EOSE | MACD | 2025-08-15 | 2025-08-29 | 2025-11-21 | 134.9% | 2025-11-05, 2025-11-10, 2025-11-20 | [view](charts/EOSE.html) |
| USAR | RSI-50 | 2025-08-08 | 2025-08-22 | 2025-11-07 | 52.7% | 2025-10-01, 2025-10-02, 2025-10-21 | [view](charts/USAR.html) |
| BIDU | RSI-50 | 2025-07-18 | 2025-08-01 | 2025-11-14 | 65.8% | 2025-10-02, 2025-10-07, 2025-11-10 | [view](charts/BIDU.html) |
| OPEN | MACD | 2025-07-03 | 2025-07-18 | 2025-10-17 | 656.8% | 2025-09-16, 2025-09-18, 2025-09-23 | [view](charts/OPEN.html) |
| INTC | RSI-50 | 2025-06-27 | 2025-07-11 | 2025-11-28 | 55.7% | 2025-06-27, 2025-07-08, 2025-07-21, 2025-08-12, 2025-08-13, 2025-08-14, 2025-08-15, 2025-08-18, 2025-08-22, 2025-08-25, 2025-09-10, 2025-09-11, 2025-09-12, 2025-09-15, 2025-09-17, 2025-09-18, 2025-09-23, 2025-09-24, 2025-09-25, 2025-10-01, 2025-10-08, 2025-10-15, 2025-10-17, 2025-10-24, 2025-10-27, 2025-10-28, 2025-11-04, 2025-11-13, 2025-11-17 | [view](charts/INTC.html) |
| APLD | MACD | 2025-06-27 | 2025-07-11 | 2025-11-14 | 134.9% | 2025-07-09, 2025-07-15, 2025-07-17, 2025-07-18, 2025-07-31, 2025-11-14 | [view](charts/APLD.html) |
| RKLB | MACD | 2025-06-20 | 2025-07-03 | 2025-08-22 | 37.4% | 2025-06-23, 2025-07-01, 2025-08-15, 2025-08-22 | [view](charts/RKLB.html) |
| CRDO | MACD | 2025-06-20 | 2025-07-03 | 2025-10-03 | 54.8% | 2025-07-09 | [view](charts/CRDO.html) |
| FUTU | MACD | 2025-06-13 | 2025-06-27 | 2025-09-26 | 37.8% | 2025-08-22 | [view](charts/FUTU.html) |
| RIOT | RSI-50 | 2025-06-06 | 2025-06-20 | 2025-11-14 | 84.4% | 2025-11-03 | [view](charts/RIOT.html) |
| IREN | RSI-50 | 2025-05-23 | 2025-06-06 | 2025-11-14 | 402.3% | 2025-10-30, 2025-11-13, 2025-11-14 | [view](charts/IREN.html) |
| MU | RSI-50 | 2025-05-16 | 2025-05-30 | 2025-11-28 | 84.5% | 2025-05-23, 2025-05-30, 2025-06-05, 2025-08-01, 2025-08-08, 2025-08-12, 2025-09-19, 2025-09-22, 2025-09-24, 2025-09-25, 2025-09-30, 2025-10-01, 2025-10-07, 2025-10-16, 2025-10-23, 2025-10-29, 2025-11-04, 2025-11-05, 2025-11-07, 2025-11-18, 2025-11-19, 2025-11-20, 2025-11-21, 2025-11-25 | [view](charts/MU.html) |
| HUT | RSI-50 | 2025-05-16 | 2025-05-30 | 2025-11-21 | 125.7% | 2025-07-31, 2025-10-02 | [view](charts/HUT.html) |
| ALAB | RSI-50 | 2025-05-16 | 2025-05-30 | 2025-10-17 | 85.4% | 2025-06-23, 2025-07-09, 2025-07-17, 2025-07-24, 2025-07-30, 2025-08-20, 2025-09-05, 2025-10-16, 2025-10-17 | [view](charts/ALAB.html) |
| AMKR | MACD | 2025-05-09 | 2025-05-23 | 2025-12-19 | 68.2% | 2025-09-22 | [view](charts/AMKR.html) |
| GLD | MACD | 2025-02-14 | 2025-02-28 | 2025-05-02 | 47.1% | 2025-03-13, 2025-03-17, 2025-03-19, 2025-03-21, 2025-03-25, 2025-03-27, 2025-04-07, 2025-04-09, 2025-04-10, 2025-04-14, 2025-04-16, 2025-04-17, 2025-04-22, 2025-04-23, 2025-04-24, 2025-04-30 | [view](charts/GLD.html) |
| UVXY | MACD | 2025-01-31 | 2025-02-14 | 2025-05-30 | 48.5% | 2025-04-10 | [view](charts/UVXY.html) |

## No daily archive rows

ABAT, ABTC, ACHR, AEM, AEO, AMDL, ARKK, ASAN, AU, BA, BABA, BE, BMNR, BNO, BOX, BYND, C, CAT, CBRS, CDE, COHR, COPX, CRCL, CRM, CRSR, CVNA, CVX, DELL, DNUT, DRAM, EAT, EH, ENVX, ETHA, EWJ, EWY, F, FCEL, FCX, FIG, GDX, GME, HIMS, HIVE, HL, HLT, HNGE, HPE, IBIT, IBM, IMSR, INDA, INFQ, IONQ, IWM, JEF, JKS, JPM, KB, KODK, KRE, KYIV, LAC, LMND, LUMN, MAGS, MO, MP, MRAM, MT, MUR, NEM, NET, NIO, NKE, NOC, NOK, NOW, NTR, NVDL, OBE, OKLO, ORCL, OWL, PALL, PPLT, Q, QQQ, QS, QTUM, RBLX, RDDT, RDW, RELL, RKT, RR, SATL, SCCO, SE, SHAZ, SKYT, SLV, SMH, SMR, SNAP, SNDQ, SNOW, SOXS, SPCE, SPY, STLA, TDOC, TE, TGT, TIGR, TLT, TM, TSM, TTE, U, UAMY, UEC, UMC, UNH, USO, UUUU, VET, VST, WEAT, WLAC, WMT, WOLF, XLE, XLF, XOM, XPEV, XYZ, YINN
