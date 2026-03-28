export interface BacktestSession {
  id: string;
  status: string;
  created_at: string;
  updated_at: string;
  execution_duration: number | null;
  net_profit_percentage: number | null;
  strategy_name: string | null;
  state: SessionState | null;
  title: string | null;
  description: string | null;
  equity_curve_sample: number[][] | null;
}

export interface SessionState {
  form?: {
    exchange: string;
    routes: Array<{ symbol: string; timeframe: string; strategy: string }>;
    data_routes: Array<{ symbol: string; timeframe: string }>;
    start_date: string;
    finish_date: string;
  };
}

export interface BacktestSessionDetail extends BacktestSession {
  metrics: BacktestMetrics | null;
  equity_curve: number[][] | null;
  trades: Trade[] | null;
  hyperparameters: Record<string, any> | null;
  has_chart_data: boolean;
  regime_periods: RegimePeriod[] | null;
}

export interface BacktestMetrics {
  total: number;
  total_winning_trades: number;
  total_losing_trades: number;
  starting_balance: number;
  finishing_balance: number;
  win_rate: number;
  ratio_avg_win_loss: number;
  longs_count: number;
  longs_percentage: number;
  shorts_count: number;
  shorts_percentage: number;
  fee: number;
  net_profit: number;
  net_profit_percentage: number;
  average_win: number;
  average_loss: number;
  max_drawdown: number;
  annual_return: number;
  sharpe_ratio: number;
  calmar_ratio: number;
  sortino_ratio: number;
  omega_ratio: number;
  total_open_trades: number;
  open_pl: number;
  winning_streak: number;
  losing_streak: number;
  largest_winning_trade: number;
  largest_losing_trade: number;
  average_holding_period: number;
  profit_factor: number;
  benchmark?: {
    buy_and_hold_return_percentage: number;
    strat_vs_buy_and_hold: number;
  };
}

export interface Trade {
  id: number;
  strategy_name: string;
  symbol: string;
  type: "long" | "short";
  entry_price: number;
  exit_price: number;
  take_profit_at: number;
  stop_loss_at: number;
  qty: number;
  fee: number;
  reward_risk_ratio: number;
  PNL: number;
  PNL_percentage: number;
  holding_period: number;
  opened_at: number;
  closed_at: number;
}

export interface RegimePeriod {
  start: number;
  end: number;
  regime: string;
  color: string;
}

export interface ChartData {
  candles_chart: number[][];
  orders_chart: OrderChart[];
  add_line_to_candle_chart: any[];
  add_extra_line_chart: any[];
  add_horizontal_line_to_candle_chart: any[];
  add_horizontal_line_to_extra_chart: any[];
}

export interface OrderChart {
  time: number;
  price: number;
  type: string;
  flag: string;
}

export interface OptimizationSession {
  id: string;
  status: string;
  created_at: string;
  updated_at: string;
  execution_duration: number | null;
  best_trials: OptimizationTrial[] | null;
  strategy_name: string | null;
  state: SessionState | null;
}

export interface OptimizationTrial {
  rank: number;
  dna: string;
  fitness: number;
  training_log: Record<string, any>;
  testing_log: Record<string, any>;
  parameters: Record<string, any>;
}

export interface CandleExisting {
  exchange: string;
  symbol: string;
  start_date: string;
  end_date: string;
}
