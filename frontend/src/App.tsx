import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import TabBar from './components/TabBar'
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
          <Route path="*" element={<Navigate to="/seasons" replace />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}
