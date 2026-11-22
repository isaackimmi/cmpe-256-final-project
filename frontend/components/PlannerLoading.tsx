export function PlannerLoading() {
  return (
    <section>
      <h1>Plan your visit</h1>
      <span className="section-title">Destination</span>
      <div
        className="loading-placeholder field-placeholder"
        aria-hidden="true"
      />
      <section className="history-section">
        <h2>Previously visited destinations</h2>
        <p role="status">Loading your trip…</p>
        <div
          className="loading-placeholder field-placeholder"
          aria-hidden="true"
        />
        <div className="visits" aria-hidden="true" />
      </section>
      <button className="primary" disabled>
        Find places
      </button>
    </section>
  );
}
