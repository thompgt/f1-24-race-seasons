import { NavLink } from 'react-router-dom'

import './TabBar.css'

const TABS = [
  { to: '/seasons', label: 'Seasons' },
  { to: '/historical', label: 'Historical Stats' },
  { to: '/ratings', label: 'Ratings' },
  { to: '/method', label: 'Method' },
]

export default function TabBar() {
  return (
    <header className="tabbar">
      <div className="tabbar-inner">
        <span className="wordmark">
          F1 <strong>24-race</strong> seasons
        </span>
        <nav aria-label="Sections">
          {TABS.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              className={({ isActive }) => (isActive ? 'tab active' : 'tab')}
            >
              {tab.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </header>
  )
}
