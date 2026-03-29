import streamlit as st
import pandas as pd
import psycopg2

# --- DATABASE SETUP ---
# Securely fetch the database URL from Streamlit's hidden secrets
DB_URL = st.secrets["DATABASE_URL"]

@st.cache_resource
def get_db_connection():
    # Connect to Neon PostgreSQL
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True # Ensures changes are saved instantly
    
    with conn.cursor() as c:
        # Create tables using PostgreSQL syntax
        c.execute('''CREATE TABLE IF NOT EXISTS tournaments
                     (id SERIAL PRIMARY KEY, name TEXT UNIQUE, fee REAL, total_matches INTEGER, deadline INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS players
                     (id SERIAL PRIMARY KEY, name TEXT, tournament_id INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS payments
                     (id SERIAL PRIMARY KEY, player_id INTEGER, tournament_id INTEGER, amount REAL, match_number INTEGER, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    return conn

conn = get_db_connection()

# --- HELPER FUNCTIONS ---
def get_tournaments():
    return pd.read_sql_query("SELECT * FROM tournaments", conn)

def get_players(tournament_id):
    return pd.read_sql_query(f"SELECT * FROM players WHERE tournament_id = {tournament_id}", conn)

# --- UI SETUP ---
st.set_page_config(page_title="Team Finance Manager", page_icon="🏏", layout="wide")
st.title("🏏 Team Finance & Tournament Manager")

# --- SIDEBAR: TOURNAMENT CREATION ---
with st.sidebar:
    st.header("🏆 Create New Tournament")
    with st.form("new_tournament"):
        t_name = st.text_input("Tournament Name (e.g., Ash Cup)")
        t_fee = st.number_input("Total Entry Fee", min_value=0, step=1000)
        t_matches = st.number_input("Total Matches", min_value=1, step=1)
        t_deadline = st.number_input("Deadline Match No.", min_value=1, step=1)
        if st.form_submit_button("Add Tournament"):
            if t_name:
                try:
                    with conn.cursor() as c:
                        c.execute("INSERT INTO tournaments (name, fee, total_matches, deadline) VALUES (%s, %s, %s, %s)", 
                                  (t_name, t_fee, t_matches, t_deadline))
                    st.success(f"'{t_name}' created!")
                    st.rerun()
                except psycopg2.IntegrityError:
                    st.error("Tournament name already exists.")
            else:
                st.error("Tournament name is required.")

# --- MAIN APP ---
tournaments_df = get_tournaments()

if tournaments_df.empty:
    st.info("👈 Please create your first tournament in the sidebar to get started.")
else:
    # 1. Select Active Tournament
    t_names = tournaments_df['name'].tolist()
    active_t_name = st.selectbox("Select Active Tournament", t_names)
    
    active_t = tournaments_df[tournaments_df['name'] == active_t_name].iloc[0]
    t_id = int(active_t['id'])
    
    tab1, tab2, tab3 = st.tabs(["📊 Dashboard & Exports", "💸 Record Payment", "👥 Manage Roster"])
    
    # --- TAB 3: MANAGE ROSTER ---
    with tab3:
        st.subheader(f"Add Players to {active_t_name}")
        with st.form("add_player"):
            p_name = st.text_input("Player Name")
            if st.form_submit_button("Add Player"):
                if p_name:
                    with conn.cursor() as c:
                        c.execute("INSERT INTO players (name, tournament_id) VALUES (%s, %s)", (p_name, t_id))
                    st.success(f"{p_name} added to roster!")
                    st.rerun()
                else:
                    st.error("Name cannot be empty.")
        
        st.write("**Current Roster**")
        players_df = get_players(t_id)
        if not players_df.empty:
            st.dataframe(players_df[['name']].rename(columns={'name': 'Player Name'}), hide_index=True)
        else:
            st.write("No players added yet.")

    # --- TAB 2: RECORD PAYMENT ---
    with tab2:
        st.subheader("Log a New Payment")
        players_df = get_players(t_id)
        
        if players_df.empty:
            st.warning("Please add players in the 'Manage Roster' tab first.")
        else:
            with st.form("payment_form"):
                col1, col2, col3 = st.columns(3)
                player_dict = dict(zip(players_df.name, players_df.id))
                
                with col1:
                    selected_p_name = st.selectbox("Player", list(player_dict.keys()))
                with col2:
                    amount = st.number_input("Amount Paid", min_value=0, step=500)
                with col3:
                    match_num = st.number_input("For Match #", min_value=1, max_value=int(active_t['total_matches']), step=1)
                
                if st.form_submit_button("Submit Payment"):
                    if amount > 0:
                        p_id = int(player_dict[selected_p_name])
                        with conn.cursor() as c:
                            c.execute("INSERT INTO payments (player_id, tournament_id, amount, match_number) VALUES (%s, %s, %s, %s)", 
                                      (p_id, t_id, amount, match_num))
                        st.success(f"Recorded {amount} for {selected_p_name}!")
                        st.rerun()
                    else:
                        st.error("Amount must be greater than 0.")

    # --- TAB 1: DASHBOARD & EXPORTS ---
    with tab1:
        with conn.cursor() as c:
            c.execute("SELECT SUM(amount) FROM payments WHERE tournament_id = %s", (t_id,))
            total_collected = c.fetchone()[0] or 0.0
            
        remaining = active_t['fee'] - total_collected
        
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Tournament Fee", f"{active_t['fee']:,.0f}")
        col_b.metric("Collected", f"{total_collected:,.0f}")
        col_c.metric("Remaining Balance", f"{remaining:,.0f}")
        
        st.progress(float(min(total_collected / active_t['fee'], 1.0)))
        
        target_per_match = active_t['fee'] / active_t['deadline']
        st.info(f"Target: Collect ~{target_per_match:,.0f} per match to clear dues by Match {int(active_t['deadline'])}.")
        
        st.divider()
        
        st.subheader("Payment History")
        history_query = f"""
            SELECT p.name as Player, pay.amount as Amount, pay.match_number as "Match #", pay.date as "Date"
            FROM payments pay
            JOIN players p ON pay.player_id = p.id
            WHERE pay.tournament_id = {t_id}
            ORDER BY pay.date DESC
        """
        history_df = pd.read_sql_query(history_query, conn)
        
        if not history_df.empty:
            st.dataframe(history_df, use_container_width=True, hide_index=True)
            
            csv = history_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label=f"📥 Download {active_t_name} Data (CSV)",
                data=csv,
                file_name=f"{active_t_name.replace(' ', '_').lower()}_payments.csv",
                mime='text/csv',
            )
        else:
            st.write("No payments recorded for this tournament yet.")
