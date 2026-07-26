import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import TabBar from './components/TabBar'
import DriverPage from './pages/DriverPage'
import HistoricalPage from './pages/HistoricalPage'
import MethodPage from './pages/MethodPage'
import RatingsPage from './pages/RatingsPage'
import SeasonPage from './pages/SeasonPage'

export default function App() {
  return (
    <BrowserRouter>
      <TabBar />
      <main className="app">
        <Routes>
          <Route path="/" element={<Navigate to="/seasons" replace />} />
          <Route path="/seasons" element={<SeasonPage />} />
          <Route path="/seasons/:year" element={<SeasonPage />} />
          <Route path="/historical" element={<HistoricalPage />} />
          <Route path="/ratings" element={<RatingsPage />} />
          <Route path="/method" element={<MethodPage />} />
          <Route path="/drivers/:driverId" element={<DriverPage />} />
          <Route path="*" element={<Navigate to="/seasons" replace />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}
