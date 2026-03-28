"use client";
import useSWR from "swr";
import { fetchCandlesExisting } from "@/lib/api";

const ALL_SYMBOLS = [
  "BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT",
  "DOGE-USDT", "ADA-USDT", "AVAX-USDT", "LINK-USDT", "DOT-USDT",
];

export default function DataPage() {
  const { data: existing, error, isLoading } = useSWR("candles-existing", fetchCandlesExisting, {
    revalidateOnFocus: false,
  });

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-[var(--red)]/10 border border-[var(--red)]/30 rounded-lg p-4 text-[var(--red)]">
          Could not connect to OpenQuant server at localhost:9000.
        </div>
      </div>
    );
  }

  const existingMap = new Map(
    (existing ?? []).map((c) => [c.symbol, c])
  );

  return (
    <div className="p-6">
      <h1 className="text-lg font-semibold text-[var(--text-heading)] mb-5">
        Candle Data Coverage
      </h1>

      {isLoading ? (
        <div className="grid grid-cols-5 gap-3">
          {[...Array(10)].map((_, i) => (
            <div key={i} className="h-24 bg-[var(--bg-surface)] rounded-lg animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-5 gap-3">
          {ALL_SYMBOLS.map((symbol) => {
            const data = existingMap.get(symbol);
            const hasData = !!data;
            const barColor = hasData ? "var(--green)" : "var(--border)";

            return (
              <div
                key={symbol}
                className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-3.5"
              >
                <div className="font-semibold text-sm mb-1">{symbol}</div>
                <div className="text-[11px] text-[var(--text-secondary)]">
                  {hasData
                    ? `${data.start_date} - ${data.end_date}`
                    : "Not imported"}
                </div>
                <div className="h-1 bg-[var(--border)] rounded mt-2 overflow-hidden">
                  <div
                    className="h-full rounded transition-all"
                    style={{
                      width: hasData ? "100%" : "0%",
                      backgroundColor: barColor,
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
