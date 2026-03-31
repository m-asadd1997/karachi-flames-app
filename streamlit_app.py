import streamlit as st
import pandas as pd
import psycopg2
import time

# --- DATABASE SETUP ---
DB_URL = st.secrets["DATABASE_URL"]

@st.cache_resource
def get_db_connection():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True 
    
    with conn.cursor() as c:
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
    return pd.read_sql_query("SELECT * FROM tournaments ORDER BY id DESC", conn)

def get_players(tournament_id):
    return pd.read_sql_query(f"SELECT * FROM players WHERE tournament_id = {tournament_id} ORDER BY name ASC", conn)

def get_payments(tournament_id):
    query = """
        SELECT pay.id, p.name as player_name, pay.amount, pay.match_number, pay.date 
        FROM payments pay 
        JOIN players p ON pay.player_id = p.id 
        WHERE pay.tournament_id = %s 
        ORDER BY pay.date DESC
    """
    return pd.read_sql_query(query, conn, params=(tournament_id,))

# --- UI SETUP ---
st.set_page_config(page_title="Team Finance Manager", page_icon="🏏", layout="wide")
st.title("🏏 Team Finance & Tournament Manager")

# --- SIDEBAR: TOURNAMENTS ---
tournaments_df = get_tournaments()
t_names = tournaments_df['name'].tolist() if not tournaments_df.empty else []

with st.sidebar:
    st.header("🏆 Add Tournament")
    with st.form("new_tournament", clear_on_submit=True):
        t_name = st.text_input("Tournament Name")
        t_fee = st.number_input("Total Entry Fee", min_value=0, step=1000)
        t_matches = st.number_input("Total Matches", min_value=1, step=1)
        t_deadline = st.number_input("Deadline Match No.", min_value=1, step=1)
        
        if st.form_submit_button("Create Tournament"):
            if not t_name.strip():
                st.error("Name cannot be blank.")
            elif t_fee <= 0:
                st.error("Fee must be > 0.")
            else:
                try:
                    with conn.cursor() as c:
                        c.execute("INSERT INTO tournaments (name, fee, total_matches, deadline) VALUES (%s, %s, %s, %s)", 
                                  (t_name.strip(), t_fee, t_matches, t_deadline))
                    st.toast(f"'{t_name}' created!", icon="✅")
                    time.sleep(1)
                    st.rerun()
                except psycopg2.IntegrityError:
                    st.error("Tournament name already exists.")
                    
    # EDIT / DELETE TOURNAMENT
    if not tournaments_df.empty:
        st.divider()
        st.header("⚙️ Manage Tournaments")
        edit_t_name = st.selectbox("Select Tournament to Manage", t_names)
        edit_t = tournaments_df[tournaments_df['name'] == edit_t_name].iloc[0]
        
        with st.expander(f"Edit or Delete '{edit_t_name}'"):
            new_t_name = st.text_input("Edit Name", value=edit_t['name'], key="et_name")
            new_t_fee = st.number_input("Edit Fee", value=int(edit_t['fee']), step=1000, key="et_fee")
            
            col_u, col_d = st.columns(2)
            if col_u.button("Update Tournament"):
                with conn.cursor() as c:
                    c.execute("UPDATE tournaments SET name=%s, fee=%s WHERE id=%s", (new_t_name, new_t_fee, int(edit_t['id'])))
                st.toast("Tournament updated!", icon="🔄")
                time.sleep(1)
                st.rerun()
                
            if col_d.button("🚨 Delete", type="primary"):
                with conn.cursor() as c:
                    # Delete associated payments and players first to avoid orphans
                    c.execute("DELETE FROM payments WHERE tournament_id=%s", (int(edit_t['id']),))
                    c.execute("DELETE FROM players WHERE tournament_id=%s", (int(edit_t['id']),))
                    c.execute("DELETE FROM tournaments WHERE id=%s", (int(edit_t['id']),))
                st.toast("Tournament deleted!", icon="🗑️")
                time.sleep(1)
                st.rerun()

# --- MAIN APP ---
if tournaments_df.empty:
    st.info("👈 Please create your first tournament in the sidebar to get started.")
else:
    active_t_name = st.selectbox("Select Active Tournament Dashboard", t_names)
    active_t = tournaments_df[tournaments_df['name'] == active_t_name].iloc[0]
    t_id = int(active_t['id'])
    
    tab1, tab2, tab3 = st.tabs(["📊 Dashboard & Exports", "💸 Record & Manage Payments", "👥 Manage Roster"])
    
    # --- TAB 3: MANAGE ROSTER ---
    with tab3:
        st.subheader(f"Add Players to {active_t_name}")
        with st.form("add_player", clear_on_submit=True):
            p_name = st.text_input("Player Name")
            if st.form_submit_button("Add Player"):
                if p_name.strip():
                    with conn.cursor() as c:
                        c.execute("INSERT INTO players (name, tournament_id) VALUES (%s, %s)", (p_name.strip(), t_id))
                    st.toast(f"{p_name} added!", icon="👤")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.warning("Please enter a name.")
        
        players_df = get_players(t_id)
        if not players_df.empty:
            st.write("**Current Roster**")
            st.dataframe(players_df[['name']].rename(columns={'name': 'Player Name'}), hide_index=True)
            
            # EDIT / DELETE PLAYER
            with st.expander("✏️ Edit or Delete a Player"):
                p_dict = dict(zip(players_df.name, players_df.id))
                edit_p_name = st.selectbox("Select Player", list(p_dict.keys()))
                edit_p_id = int(p_dict[edit_p_name])
                
                new_p_name = st.text_input("New Name", value=edit_p_name)
                
                c1, c2 = st.columns(2)
                if c1.button("Update Player"):
                    with conn.cursor() as c:
                        c.execute("UPDATE players SET name=%s WHERE id=%s", (new_p_name.strip(), edit_p_id))
                    st.toast("Player updated!", icon="🔄")
                    time.sleep(1)
                    st.rerun()
                
                if c2.button("🚨 Delete Player", type="primary"):
                    with conn.cursor() as c:
                        c.execute("DELETE FROM payments WHERE player_id=%s", (edit_p_id,)) # Delete their payments first
                        c.execute("DELETE FROM players WHERE id=%s", (edit_p_id,))
                    st.toast("Player and their payments deleted!", icon="🗑️")
                    time.sleep(1)
                    st.rerun()
        else:
            st.info("No players added yet.")

    # --- TAB 2: PAYMENTS ---
    with tab2:
        st.subheader("Log a New Payment")
        if players_df.empty:
            st.warning("Add players in the 'Manage Roster' tab first.")
        else:
            with st.form("payment_form", clear_on_submit=True):
                col1, col2, col3 = st.columns(3)
                p_dict = dict(zip(players_df.name, players_df.id))
                
                with col1:
                    selected_p = st.selectbox("Select Player", list(p_dict.keys()))
                with col2:
                    amount = st.number_input("Amount (PKR)", min_value=0, step=500)
                with col3:
                    match_num = st.number_input("Match #", min_value=1, max_value=int(active_t['total_matches']), step=1)
                
                if st.form_submit_button("Submit Payment"):
                    if amount > 0:
                        with conn.cursor() as c:
                            c.execute("INSERT INTO payments (player_id, tournament_id, amount, match_number) VALUES (%s, %s, %s, %s)", 
                                      (int(p_dict[selected_p]), t_id, amount, match_num))
                        st.toast(f"Recorded {amount:,.0f} PKR!", icon="💸")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Amount must be > 0.")

            # EDIT / DELETE PAYMENT
            payments_df = get_payments(t_id)
            if not payments_df.empty:
                st.divider()
                with st.expander("✏️ Edit or Delete a Recorded Payment"):
                    # Create a readable list of payments for the dropdown
                    pay_options = []
                    for _, row in payments_df.iterrows():
                        date_str = pd.to_datetime(row['date']).strftime('%b %d')
                        pay_options.append(f"ID {row['id']}: {row['player_name']} - {row['amount']} PKR (Match {row['match_number']} on {date_str})")
                    
                    selected_pay_str = st.selectbox("Select Payment to Modify", pay_options)
                    
                    # Extract ID from the string (e.g., "ID 5: Asad...")
                    edit_pay_id = int(selected_pay_str.split(":")[0].replace("ID ", ""))
                    edit_pay_row = payments_df[payments_df['id'] == edit_pay_id].iloc[0]
                    
                    c_a, c_b = st.columns(2)
                    with c_a:
                        new_amt = st.number_input("Edit Amount", value=float(edit_pay_row['amount']), step=500.0)
                    with c_b:
                        new_match = st.number_input("Edit Match #", value=int(edit_pay_row['match_number']), step=1)
                    
                    btn1, btn2 = st.columns(2)
                    if btn1.button("Update Payment"):
                        with conn.cursor() as c:
                            c.execute("UPDATE payments SET amount=%s, match_number=%s WHERE id=%s", (new_amt, new_match, edit_pay_id))
                        st.toast("Payment updated!", icon="🔄")
                        time.sleep(1)
                        st.rerun()
                        
                    if btn2.button("🚨 Delete Payment", type="primary"):
                        with conn.cursor() as c:
                            c.execute("DELETE FROM payments WHERE id=%s", (edit_pay_id,))
                        st.toast("Payment deleted!", icon="🗑️")
                        time.sleep(1)
                        st.rerun()

    # --- TAB 1: DASHBOARD ---
    with tab1:
        payments_df = get_payments(t_id)
        total_collected = payments_df['amount'].sum() if not payments_df.empty else 0.0
        remaining = active_t['fee'] - total_collected
        
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Tournament Fee", f"{active_t['fee']:,.0f} PKR")
        col_b.metric("Total Collected", f"{total_collected:,.0f} PKR")
        col_c.metric("Remaining Balance", f"{remaining:,.0f} PKR")
        
        progress_val = float(min(total_collected / active_t['fee'], 1.0)) if active_t['fee'] > 0 else 0.0
        st.progress(progress_val)
        
        st.divider()
        st.subheader("Transaction History")
        
        if not payments_df.empty:
            display_df = payments_df[['player_name', 'amount', 'match_number', 'date']].copy()
            display_df.columns = ["Player", "Amount (PKR)", "Match #", "Date Recorded"]
            display_df['Date Recorded'] = pd.to_datetime(display_df['Date Recorded']).dt.strftime('%Y-%m-%d %I:%M %p')
            
            st.dataframe(display_df, use_container_width=True, hide_index=True)
            
            csv = display_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label=f"📥 Download Data (CSV)",
                data=csv,
                file_name=f"{active_t_name.replace(' ', '_').lower()}_payments.csv",
                mime='text/csv',
                type="primary"
            )
        else:
            st.info("No payments recorded yet.")
