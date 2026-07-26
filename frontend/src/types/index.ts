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
export type Metric =
  | 'wins'
  | 'quality_wins'
  | 'podiums'
  | 'poles'
  | 'points'
  | 'championships'

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

export interface MethodStep {
  title: string
  detail: string
}

export interface Caveat {
  key: string
  title: string
  detail: string
}

export interface Meta {
  run: RunInfo
  first_year: number
  last_year: number
  target_races: number
  shortest_season_year: number
  shortest_season_races: number
  longest_season_year: number
  longest_season_races: number
  data_sources: string[]
  method: MethodStep[]
  caveats: Caveat[]
}

export interface DriverSeason {
  year: number
  constructor: ConstructorRef | null
  races: number
  actual_wins: number
  actual_podiums: number
  actual_poles: number
  actual_points: number
  actual_quality_wins: number
  scaled_wins: number
  quality_wins: SimStat
  wins: SimStat
  podiums: SimStat
  poles: SimStat
  points: SimStat
  p_champion: number
  is_actual_champion: boolean
}

export interface CareerTotals {
  seasons: number
  first_year: number
  last_year: number
  races: number
  actual_wins: number
  actual_podiums: number
  actual_poles: number
  actual_points: number
  actual_championships: number
  scaled_wins: number
  scaled_podiums: number
  scaled_poles: number
  actual_quality_wins: number
  quality_wins: SimStat
  wins: SimStat
  podiums: SimStat
  poles: SimStat
  points: SimStat
  championships: SimStat
  championships_at_least: Record<number, number>
}

export interface DriverDetail {
  driver: DriverRef
  dob: string | null
  run: RunInfo
  career: CareerTotals
  seasons: DriverSeason[]
  rating: DriverRating | null
}

/** Which column the ratings table is ordered by. */
export type RatingSort =
  | 'peak'
  | 'teammate'
  | 'vs_field'
  | 'quality_wins'
  | 'difficulty'

export interface RatingRow {
  rank: number
  driver_id: number
  name: string
  nationality: string | null
  first_year: number
  last_year: number
  races: number
  peak_rating: number
  peak_teammate_rating: number
  peak_vs_field: number
  final_rating: number
  wins: number
  quality_wins: number
  mean_win_difficulty: number | null
  teammate_races: number
  teammate_wins: number
}

export interface RatingBoard {
  sort: RatingSort
  min_races: number
  total: number
  rows: RatingRow[]
}

export interface NotableWin {
  race_id: number
  year: number
  race_name: string
  driver_id: number
  driver_name: string
  constructor_name: string | null
  difficulty: number
  expected_position: number
  starters: number
}

export interface RatingPoint {
  race_id: number
  year: number
  rating: number
  teammate_rating: number
  position: number | null
  win_difficulty: number | null
}

export interface DriverRating {
  peak_rating: number
  peak_teammate_rating: number
  peak_vs_field: number
  final_rating: number
  final_teammate_rating: number
  wins: number
  quality_wins: number
  mean_win_difficulty: number | null
  teammate_races: number
  teammate_wins: number
  teammate_rank: number | null
  trace: RatingPoint[]
}
