import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { DrawPage } from './pages/DrawPage'
import { HomePage } from './pages/HomePage'
import { PublicResultPage } from './pages/PublicResultPage'

function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/draw/:id" element={<DrawPage />} />
          <Route path="/result/:publicId" element={<PublicResultPage />} />
        </Routes>
      </div>
    </BrowserRouter>
  )
}

export default App
