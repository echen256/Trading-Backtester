# 3-Day adaptive-MACD strong trends — entered assets

This catalogue uses filled **BUY** orders from 2025 and 2026 as entries. It includes only trend periods containing at least one such entry date.

## Definition

- Start: first 3-day close where adaptive MACD and its signal are both above zero.
- Confirmation: the first completed negative-histogram pullback after start keeps the signal strictly above zero; the confirmation date is its first non-negative histogram bar.
- Strength: the trend sets a new high in the signal line versus all earlier available 3-day history, and contains at least eight consecutive positive, increasing histogram bars (the light-blue sequence).
- End: first bar the signal reaches or falls below zero; otherwise the period remains active through the latest bar.

Scanned 236 entered underlyings; 138 had no daily archive rows. The signal ATH is relative to the downloaded history (2020-01-01 onward), not a vendor-guaranteed lifetime series. ‘Open through latest data’ means the available archive has no qualifying end signal, not that the trend is necessarily still live today.

## Qualifying periods

| Asset | Start | Confirmed | End | Signal ATH | Light-blue streak | Entry dates in period | Chart |
| --- | --- | --- | --- | --- | ---: | --- | --- |
| MSTR | 2026-01-15 | 2026-02-27 | 2026-06-16 | 2026-05-21 (0.5810) | 9 | 2026-01-29, 2026-02-05, 2026-02-11, 2026-02-18, 2026-03-12, 2026-05-01, 2026-05-05, 2026-05-07, 2026-05-12, 2026-05-28, 2026-06-01, 2026-06-02, 2026-06-03, 2026-06-05, 2026-06-11 | [view](charts/MSTR.html) |
| AMD | 2025-03-28 | 2025-04-25 | 2025-09-02 | 2025-07-07 (0.7595) | 10 | 2025-06-17, 2025-06-24 | [view](charts/AMD.html) |

## Micro trends

A micro trend starts when either the adaptive MACD crosses above zero or 14-period RSI crosses above 50 (RSI−50 crosses zero), remains in force for at least three 3-day bars, and expands 14-period ATR by at least 33% from the start. It ends on the first negative adaptive-MACD histogram bar.

| Asset | Trigger | Start | Qualified | End | Max ATR expansion | Entry dates in period | Chart |
| --- | --- | --- | --- | --- | ---: | --- | --- |
| FLNC | RSI-50 | 2026-05-08 | 2026-05-15 | open through latest data | 42.5% | 2026-06-01 | [view](charts/FLNC.html) |
| MU | MACD | 2026-04-21 | 2026-04-27 | 2026-05-18 | 63.4% | 2026-04-22, 2026-04-23, 2026-04-27, 2026-04-28, 2026-05-05, 2026-05-06, 2026-05-07, 2026-05-08, 2026-05-12, 2026-05-18 | [view](charts/MU.html) |
| QCOM | MACD | 2026-04-17 | 2026-04-24 | 2026-06-08 | 280.6% | 2026-04-24, 2026-04-30, 2026-05-06, 2026-05-08, 2026-05-12, 2026-05-14, 2026-05-15, 2026-05-20, 2026-05-21, 2026-05-26, 2026-05-28, 2026-05-29, 2026-06-01, 2026-06-05 | [view](charts/QCOM.html) |
| POET | MACD | 2026-04-17 | 2026-04-24 | 2026-05-06 | 118.4% | 2026-04-22, 2026-04-27 | [view](charts/POET.html) |
| IREN | RSI-50 | 2026-04-15 | 2026-04-21 | 2026-06-08 | 42.4% | 2026-04-22, 2026-04-24, 2026-04-27, 2026-04-29, 2026-05-01, 2026-05-04, 2026-05-05, 2026-05-06, 2026-05-07, 2026-05-08, 2026-05-14, 2026-05-15, 2026-05-20, 2026-05-21, 2026-05-26, 2026-05-27, 2026-05-28, 2026-05-29, 2026-06-01, 2026-06-03, 2026-06-04, 2026-06-05 | [view](charts/IREN.html) |
| CIFR | RSI-50 | 2026-04-09 | 2026-04-15 | 2026-06-08 | 36.5% | 2026-05-13 | [view](charts/CIFR.html) |
| AMD | RSI-50 | 2026-04-02 | 2026-04-09 | 2026-05-22 | 100.6% | 2026-05-01, 2026-05-04, 2026-05-22 | [view](charts/AMD.html) |
| INTC | RSI-50 | 2026-03-25 | 2026-03-31 | 2026-05-18 | 163.7% | 2026-03-26, 2026-03-27, 2026-03-31, 2026-04-02, 2026-04-06, 2026-04-14, 2026-04-24, 2026-04-29, 2026-05-05, 2026-05-15 | [view](charts/INTC.html) |
| NVTS | RSI-50 | 2026-03-13 | 2026-03-19 | 2026-06-02 | 164.4% | 2026-05-11, 2026-05-13, 2026-05-14, 2026-05-19, 2026-05-21, 2026-05-22 | [view](charts/NVTS.html) |
| CAR | MACD | 2026-02-17 | 2026-02-23 | 2026-04-27 | 1364.0% | 2026-04-21, 2026-04-22, 2026-04-23 | [view](charts/CAR.html) |
| SNDK | MACD | 2026-01-06 | 2026-01-12 | 2026-02-05 | 98.0% | 2026-02-02, 2026-02-04 | [view](charts/SNDK.html) |
| MU | MACD | 2025-12-24 | 2025-12-31 | 2026-02-05 | 47.0% | 2026-01-02, 2026-01-09, 2026-02-03 | [view](charts/MU.html) |
| ASTS | MACD | 2025-12-22 | 2025-12-26 | 2026-02-05 | 41.0% | 2025-12-22 | [view](charts/ASTS.html) |
| NXT | RSI-50 | 2025-12-16 | 2025-12-22 | 2026-02-26 | 33.3% | 2025-12-22 | [view](charts/NXT.html) |
| INTC | MACD | 2025-12-16 | 2025-12-22 | 2026-01-30 | 45.3% | 2026-01-22 | [view](charts/INTC.html) |
| GLD | MACD | 2025-12-16 | 2025-12-22 | 2026-02-02 | 94.0% | 2025-12-17, 2025-12-18, 2025-12-24, 2026-01-09, 2026-01-14, 2026-01-21, 2026-01-23, 2026-02-02 | [view](charts/GLD.html) |
| DJT | MACD | 2025-12-04 | 2025-12-10 | 2026-01-21 | 44.1% | 2026-01-09 | [view](charts/DJT.html) |
| USAR | MACD | 2025-09-29 | 2025-10-03 | 2025-10-23 | 140.5% | 2025-10-01, 2025-10-02, 2025-10-21 | [view](charts/USAR.html) |
| AVAV | RSI-50 | 2025-09-08 | 2025-09-12 | 2025-10-20 | 61.3% | 2025-09-17 | [view](charts/AVAV.html) |
| MU | MACD | 2025-09-05 | 2025-09-11 | 2025-10-10 | 51.9% | 2025-09-19, 2025-09-22, 2025-09-24, 2025-09-25, 2025-09-30, 2025-10-01, 2025-10-07 | [view](charts/MU.html) |
| NXT | MACD | 2025-09-02 | 2025-09-08 | 2025-11-04 | 41.1% | 2025-09-05, 2025-09-18 | [view](charts/NXT.html) |
| INTC | MACD | 2025-08-22 | 2025-08-29 | 2025-10-14 | 40.6% | 2025-08-22, 2025-08-25, 2025-09-10, 2025-09-11, 2025-09-12, 2025-09-15, 2025-09-17, 2025-09-18, 2025-09-23, 2025-09-24, 2025-09-25, 2025-10-01, 2025-10-08 | [view](charts/INTC.html) |
| BIDU | RSI-50 | 2025-08-22 | 2025-08-29 | 2025-10-02 | 108.9% | 2025-10-02 | [view](charts/BIDU.html) |
| ASML | RSI-50 | 2025-08-22 | 2025-08-29 | 2025-10-14 | 46.8% | 2025-09-05, 2025-10-13, 2025-10-14 | [view](charts/ASML.html) |
| QUBT | MACD | 2025-05-20 | 2025-05-29 | 2025-07-16 | 57.6% | 2025-06-09, 2025-06-10, 2025-06-20 | [view](charts/QUBT.html) |
| APLD | MACD | 2025-05-14 | 2025-05-20 | 2025-07-01 | 54.3% | 2025-06-06 | [view](charts/APLD.html) |
| RKLB | RSI-50 | 2025-04-25 | 2025-05-02 | 2025-07-28 | 34.9% | 2025-05-14, 2025-05-15, 2025-05-27, 2025-05-28, 2025-06-23, 2025-07-01 | [view](charts/RKLB.html) |
| FSLR | MACD | 2025-04-17 | 2025-04-25 | 2025-06-20 | 37.2% | 2025-04-22, 2025-04-23, 2025-04-30, 2025-05-21, 2025-06-05, 2025-06-17 | [view](charts/FSLR.html) |
| BILI | RSI-50 | 2025-02-07 | 2025-02-13 | 2025-03-28 | 43.6% | 2025-02-20, 2025-02-21 | [view](charts/BILI.html) |
| FUTU | MACD | 2025-01-31 | 2025-02-07 | 2025-03-06 | 46.8% | 2025-02-12, 2025-02-13, 2025-02-20, 2025-03-04, 2025-03-05 | [view](charts/FUTU.html) |
| TMUS | RSI-50 | 2025-01-29 | 2025-02-04 | 2025-03-14 | 38.1% | 2025-03-11 | [view](charts/TMUS.html) |

## No daily archive rows

ABAT, ABTC, ACHR, AEM, AEO, AMDL, ARKK, ASAN, AU, BA, BABA, BE, BMNR, BNO, BOX, BYND, C, CAT, CBRS, CDE, COHR, COPX, CRCL, CRM, CRSR, CVNA, CVX, DELL, DNUT, DRAM, EAT, EH, ENVX, ETHA, EWJ, EWY, F, FCEL, FCX, FIG, GDX, GME, HIMS, HIVE, HL, HLT, HNGE, HPE, IBIT, IBM, IMSR, INDA, INFQ, IONQ, IWM, JEF, JKS, JPM, KB, KODK, KRE, KYIV, LAC, LMND, LUMN, MAGS, MO, MP, MRAM, MT, MUR, NEM, NET, NIO, NKE, NOC, NOK, NOW, NTR, NVDL, OBE, OKLO, ORCL, OWL, PALL, PPLT, Q, QQQ, QS, QTUM, RBLX, RDDT, RDW, RELL, RKT, RR, SATL, SCCO, SE, SHAZ, SKYT, SLV, SMH, SMR, SNAP, SNDQ, SNOW, SOXS, SPCE, SPY, STLA, TDOC, TE, TGT, TIGR, TLT, TM, TSM, TTE, U, UAMY, UEC, UMC, UNH, USO, UUUU, VET, VST, WEAT, WLAC, WMT, WOLF, XLE, XLF, XOM, XPEV, XYZ, YINN
