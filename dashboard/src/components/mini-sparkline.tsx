interface MiniSparklineProps {
  data: number[][] | null;
  width?: number;
  height?: number;
}

export function MiniSparkline({
  data,
  width = 80,
  height = 24,
}: MiniSparklineProps) {
  if (!data || data.length < 2) return null;

  const values = data.map((d) => d[1]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = height - ((v - min) / range) * (height - 4) - 2;
      return `${x},${y}`;
    })
    .join(" ");

  const isPositive = values[values.length - 1] >= values[0];

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <polyline
        points={points}
        fill="none"
        stroke={isPositive ? "var(--green)" : "var(--red)"}
        strokeWidth={1.5}
      />
    </svg>
  );
}
