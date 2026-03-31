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
            if t_name.strip() and t_fee > 0:
                try:
                    with conn.cursor() as c:
                        c.execute("INSERT INTO tournaments (name, fee, total_matches, deadline) VALUES (%s, %s, %s, %s)", 
                                  (t_name.strip(), t_fee, t_matches, t_deadline))
                    st.toast(f"'{t_name}' created!", icon="✅")
                    time.sleep(1)
                    st.rerun()
                except psycopg2.IntegrityError:
                    st.error("Tournament name already exists.")

# --- MAIN APP ---
if tournaments_df.empty:
    st.info("👈 Please create your first tournament in the sidebar to get started.")
else:
    # Top Bar selection
    col_sel, col_set = st.columns([3, 1])
    with col_sel:
        active_t_name = st.selectbox("Active Tournament Dashboard", t_names, label_visibility="collapsed")
    
    active_t = tournaments_df[tournaments_df['name'] == active_t_name].iloc[0]
    t_id = int(active_t['id'])

    # Tournament Settings Popover
    with col_set:
        with st.popover("⚙️ Tournament Settings"):
            st.write("**Edit Active Tournament**")
            new_t_name = st.text_input("Name", value=active_t['name'])
            new_t_fee = st.number_input("Fee", value=int(active_t['fee']), step=1000)
            
            if st.button("Save Settings", use_container_width=True):
                with conn.cursor() as c:
                    c.execute("UPDATE tournaments SET name=%s, fee=%s WHERE id=%s", (new_t_name, new_t_fee, t_id))
                st.toast("Settings updated!", icon="🔄")
                time.sleep(1)
                st.rerun()
            if st.button("🚨 Delete Tournament", type="primary", use_container_width=True):
                with conn.cursor() as c:
                    c.execute("DELETE FROM payments WHERE tournament_id=%s", (t_id,))
                    c.execute("DELETE FROM players WHERE tournament_id=%s", (t_id,))
                    c.execute("DELETE FROM tournaments WHERE id=%s", (t_id,))
                st.toast("Tournament wiped!", icon="🗑️")
                time.sleep(1)
                st.rerun()

    tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "💸 Manage Payments", "👥 Manage Roster"])
    
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
            
            # Read-only table for the dashboard
            st.dataframe(display_df, use_container_width=True, hide_index=True)
            
            csv = display_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Data (CSV)", data=csv, file_name=f"{active_t_name.replace(' ', '_').lower()}_payments.csv", mime='text/csv', type="primary")
        else:
            st.info("No payments recorded yet.")

    # --- TAB 2: MANAGE PAYMENTS ---
    with tab2:
        players_df = get_players(t_id)
        if players_df.empty:
            st.warning("Add players in the 'Manage Roster' tab first.")
        else:
            st.write("### ➕ Log a New Payment")
            with st.form("payment_form", clear_on_submit=True):
                col1, col2, col3 = st.columns(3)
                p_dict = dict(zip(players_df.name, players_df.id))
                
                with col1: selected_p = st.selectbox("Player", list(p_dict.keys()))
                with col2: amount = st.number_input("Amount (PKR)", min_value=0, step=500)
                with col3: match_num = st.number_input("Match #", min_value=1, max_value=int(active_t['total_matches']), step=1)
                
                if st.form_submit_button("Submit Payment"):
                    if amount > 0:
                        with conn.cursor() as c:
                            c.execute("INSERT INTO payments (player_id, tournament_id, amount, match_number) VALUES (%s, %s, %s, %s)", 
                                      (int(p_dict[selected_p]), t_id, amount, match_num))
                        st.toast(f"Recorded {amount:,.0f} PKR!", icon="💸")
                        time.sleep(1)
                        st.rerun()
            
            st.divider()
            st.write("### ✏️ Edit or Delete Records")
            st.caption("Double-click a cell to edit the Amount or Match #. Select a row (checkbox on the left) and press your **Delete** key to remove it.")
            
            if not payments_df.empty:
                disp_pay = payments_df[['id', 'player_name', 'amount', 'match_number', 'date']].copy()
                disp_pay.columns = ["id", "Player", "Amount (PKR)", "Match #", "Date"]
                
                # Interactive Data Editor
                st.data_editor(
                    disp_pay,
                    column_config={
                        "id": None, # Hide database ID visually
                        "Player": st.column_config.TextColumn(disabled=True),
                        "Date": st.column_config.DatetimeColumn(disabled=True, format="MMM DD, YYYY")
                    },
                    num_rows="dynamic",
                    key="pay_editor",
                    use_container_width=True
                )
                
                # Save button processes changes from the spreadsheet UI
                if st.button("💾 Save Changes to Database", type="primary"):
                    changes = st.session_state["pay_editor"]
                    with conn.cursor() as c:
                        # Process Edits
                        for row_idx, edit in changes["edited_rows"].items():
                            pay_id = int(disp_pay.iloc[row_idx]["id"])
                            if "Amount (PKR)" in edit:
                                c.execute("UPDATE payments SET amount=%s WHERE id=%s", (edit["Amount (PKR)"], pay_id))
                            if "Match #" in edit:
                                c.execute("UPDATE payments SET match_number=%s WHERE id=%s", (edit["Match #"], pay_id))
                        # Process Deletes
                        for row_idx in changes["deleted_rows"]:
                            pay_id = int(disp_pay.iloc[row_idx]["id"])
                            c.execute("DELETE FROM payments WHERE id=%s", (pay_id,))
                    
                    st.toast("Database updated!", icon="✅")
                    time.sleep(1)
                    st.rerun()
            else:
                st.info("No payments to edit yet.")

    # --- TAB 3: MANAGE ROSTER ---
    with tab3:
        st.write("### ➕ Add Player")
        with st.form("add_player", clear_on_submit=True):
            col_p1, col_p2 = st.columns([3, 1])
            with col_p1: p_name = st.text_input("Player Name", label_visibility="collapsed", placeholder="Enter player name...")
            with col_p2: 
                if st.form_submit_button("Add to Roster", use_container_width=True):
                    if p_name.strip():
                        with conn.cursor() as c:
                            c.execute("INSERT INTO players (name, tournament_id) VALUES (%s, %s)", (p_name.strip(), t_id))
                        st.toast(f"{p_name} added!", icon="👤")
                        time.sleep(1)
                        st.rerun()

        st.divider()
        st.write("### ✏️ Edit or Delete Players")
        st.caption("Double-click a name to fix a typo. Select a row and press **Delete** to remove a player (warning: this wipes their payments too!).")
        
        if not players_df.empty:
            disp_players = players_df[['id', 'name']].copy()
            disp_players.columns = ["id", "Player Name"]
            
            st.data_editor(
                disp_players,
                column_config={"id": None},
                num_rows="dynamic",
                key="roster_editor",
                use_container_width=True
            )
            
            if st.button("💾 Save Roster Changes", type="primary"):
                changes = st.session_state["roster_editor"]
                with conn.cursor() as c:
                    for row_idx, edit in changes["edited_rows"].items():
                        if "Player Name" in edit:
                            p_id = int(disp_players.iloc[row_idx]["id"])
                            c.execute("UPDATE players SET name=%s WHERE id=%s", (edit["Player Name"], p_id))
                    for row_idx in changes["deleted_rows"]:
                        p_id = int(disp_players.iloc[row_idx]["id"])
                        c.execute("DELETE FROM payments WHERE player_id=%s", (p_id,))
                        c.execute("DELETE FROM players WHERE id=%s", (p_id,))
                
                st.toast("Roster updated!", icon="✅")
                time.sleep(1)
                st.rerun()
        else:
            st.info("No players added yet.")
