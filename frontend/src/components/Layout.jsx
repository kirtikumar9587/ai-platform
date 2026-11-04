import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api, setToken } from "../api";

export default function Layout() {
  const [email, setEmail] = useState("");
  const nav = useNavigate();
  useEffect(() => {
    api.me().then((u) => setEmail(u.email)).catch(() => {});
  }, []);
  const logout = () => {
    setToken(null);
    nav("/login");
  };
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">Enterprise<br />Intelligence</div>
        <nav>
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/documents">Documents</NavLink>
          <NavLink to="/chat">Ask &amp; analyse</NavLink>
          <NavLink to="/logs">Logs</NavLink>
        </nav>
        <div className="who">
          <span title={email}>{email}</span>
          <button className="link" onClick={logout}>Sign out</button>
        </div>
      </aside>
      <main className="main"><Outlet /></main>
    </div>
  );
}
