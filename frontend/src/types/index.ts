export interface Health {
  status: string
  database_present: boolean
}

export interface DriverRef {
  driver_id: number
  name: string
  code: string | null
  nationality: string | null
}

export interface ConstructorRef {
  constructor_id: number
  name: string
  nationality: string | null
}

/** A simulated total: central estimate plus its 95% interval. */
export interface SimStat {
  mean: number
  median: number
  p2_5: number
  p97_5: number
}

export interface RunInfo {
  run_id: number
  created_at: string
  n_iterations: number
  target_races: number
  master_seed: number
  seasons_simulated: number
}

export interface SeasonSummary {
  year: number
  n_races: number
  n_sprints: number
  is_complete: boolean
  source: string
  actual_champion: DriverRef | null
  likeliest_champion: DriverRef | null
  likeliest_champion_probability: number
  champion_changes: boolean
}

export interface ActualTotals {
  races: number
  points: number
  points_no_fl: number
  wins: number
  podiums: number
  poles: number
  position: number | null
}

export interface ScaledTotals {
  points: number
  wins: number
  podiums: number
  poles: number
}

export interface SeasonDriverRow {
  driver: DriverRef
  constructor: ConstructorRef | null
  actual: ActualTotals
  scaled: ScaledTotals
  points: SimStat
  wins: SimStat
  podiums: SimStat
  poles: SimStat
  entries_mean: number
  entries_p2_5: number
  entries_p97_5: number
  p_champion: number
  p_top3: number
  is_actual_champion: boolean
  is_part_season: boolean
}

export interface SeasonConstructorRow {
  constructor: ConstructorRef
  actual_points: number
  actual_wins: number
  actual_podiums: number
  scaled_points: number
  scaled_wins: number
  scaled_podiums: number
  points: SimStat
  wins: SimStat
  podiums: SimStat
  p_champion: number
}

export interface ExcludedRace {
  name: string
  reason: string
}

export interface SeasonDetail {
  year: number
  n_races: number
  n_sprints: number
  target_races: number
  is_complete: boolean
  actual_champion: DriverRef | null
  excluded_races: ExcludedRace[]
  run: RunInfo
  drivers: SeasonDriverRow[]
  constructors: SeasonConstructorRow[]
}

export interface ChampionOdds {
  driver: DriverRef
  p_champion: number
  is_actual_champion: boolean
}

/** Which metric a table or leaderboard is showing. */
export type Metric = 'wins' | 'podiums' | 'poles' | 'points' | 'championships'

/** Which of the three bases a figure is drawn from. */
export type Basis = 'sim' | 'scaled' | 'actual'

export type GroupBy =
  | 'driver'
  | 'constructor'
  | 'driver_nationality'
  | 'constructor_nationality'

export interface LeaderRow {
  rank: number
  key: string
  label: string
  sublabel: string | null
  actual: number
  scaled: number
  sim: SimStat
  rank_actual: number | null
  rank_delta: number | null
  n_entities: number
  seasons_active: number | null
  first_year: number | null
  last_year: number | null
}

export interface LeaderBoard {
  metric: Metric
  group_by: GroupBy
  basis: Basis
  total: number
  min_races: number
  year_from: number | null
  year_to: number | null
  run: RunInfo
  rows: LeaderRow[]
}

export interface LeaderQuery {
  metric: Metric
  group_by: GroupBy
  basis: Basis
  min_races?: number
  year_from?: number
  year_to?: number
  limit?: number
}
