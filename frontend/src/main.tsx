import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './app/App'
import { PRODUCT_NAME } from './app/brand'
import './styles/globals.css'

document.title = PRODUCT_NAME

const rootEl = document.getElementById('root')!
ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
