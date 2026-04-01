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
        # Create core tables
        c.execute('''CREATE TABLE IF NOT EXISTS tournaments
                     (id SERIAL PRIMARY KEY, name TEXT UNIQUE, fee REAL, total_matches INTEGER, deadline INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS players
                     (id SERIAL PRIMARY KEY, name TEXT, tournament_id INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS payments
                     (id SERIAL PRIMARY KEY, player_id INTEGER, tournament_id INTEGER, amount REAL, match_number INTEGER, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    return conn

conn = get_db_connection()

# Database Migration: Safely add 'current_match' to existing databases
try:
    with conn.cursor() as c:
        c.execute("ALTER TABLE tournaments ADD COLUMN current_match INTEGER DEFAULT 1")
except psycopg2.Error:
    pass # Column already exists, safe to ignore

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

# --- CONFIRMATION MODALS ---
@st.dialog("🚨 Confirm Deletion")
def delete_tournament_modal(t_id, t_name):
    st.error(f"You are about to permanently delete **{t_name}**.")
    st.warning("This will instantly wipe ALL players and ALL payment records associated with this tournament. This cannot be undone.")
    
    col1, col2 = st.columns(2)
    if col1.button("Cancel", use_container_width=True):
        st.rerun()
    if col2.button("Yes, Delete It", type="primary", use_container_width=True):
        with conn.cursor() as c:
            c.execute("DELETE FROM payments WHERE tournament_id=%s", (t_id,))
            c.execute("DELETE FROM players WHERE tournament_id=%s", (t_id,))
            c.execute("DELETE FROM tournaments WHERE id=%s", (t_id,))
        st.toast("Tournament completely wiped!", icon="🗑️")
        time.sleep(1)
        st.rerun()

# --- UI SETUP ---
st.set_page_config(page_title="Team Finance Manager", page_icon="🏏", layout="wide")
st.title("🏏 Team Finance Manager")

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
        
        if st.form_submit_button("Create Tournament", use_container_width=True):
            if t_name.strip() and t_fee > 0:
                try:
                    with conn.cursor() as c:
                        c.execute("INSERT INTO tournaments (name, fee, total_matches, deadline, current_match) VALUES (%s, %s, %s, %s, 1)", 
                                  (t_name.strip(), t_fee, t_matches, t_deadline))
                    st.toast(f"'{t_name}' created!", icon="✅")
                    time.sleep(1)
                    st.rerun()
                except psycopg2.IntegrityError:
                    st.error("Tournament name already exists.")

# --- MAIN APP ---
if tournaments_df.empty:
    st.info("👈 Please create your first tournament in the sidebar menu to get started.")
else:
    active_t_name = st.selectbox("Active Tournament Dashboard", t_names)
    active_t = tournaments_df[tournaments_df['name'] == active_t_name].iloc[0]
    t_id = int(active_t['id'])
    # Safely get current match (defaults to 1 if missing during initial load)
    cur_match = int(active_t.get('current_match', 1))

    with st.expander("⚙️ Tournament Settings (Edit/Delete)"):
        st.caption("Update the fee/name, or delete the entire tournament.")
        new_t_name = st.text_input("Name", value=active_t['name'])
        new_t_fee = st.number_input("Fee", value=int(active_t['fee']), step=1000)
        new_t_match = st.number_input("Current Active Match", value=cur_match, min_value=1, step=1)
        
        c_save, c_del = st.columns(2)
        if c_save.button("Save Updates", use_container_width=True):
            with conn.cursor() as c:
                c.execute("UPDATE tournaments SET name=%s, fee=%s, current_match=%s WHERE id=%s", (new_t_name, new_t_fee, new_t_match, t_id))
            st.toast("Settings updated!", icon="🔄")
            time.sleep(1)
            st.rerun()
        if c_del.button("🚨 Delete", type="primary", use_container_width=True):
            delete_tournament_modal(t_id, active_t['name'])

    tab1, tab2, tab3 = st.tabs(["📊 Dash", "💸 Payments", "👥 Roster"])
    
    # --- TAB 1: DASHBOARD ---
    with tab1:
        payments_df = get_payments(t_id)
        total_collected = payments_df['amount'].sum() if not payments_df.empty else 0.0
        remaining = active_t['fee'] - total_collected
        
        # GRAND TOTALS
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Total Fee", f"{active_t['fee']:,.0f}")
        col_b.metric("Total Collected", f"{total_collected:,.0f}")
        col_c.metric("Total Remaining", f"{remaining:,.0f}")
        
        st.divider()
        
        # ACTIVE MATCH FOCUS
        st.write(f"### 🎯 Focus: Collecting for Match {cur_match}")
        target_per_match = active_t['fee'] / active_t['deadline'] if active_t['deadline'] > 0 else 0
        
        # Calculate how much was collected specifically for the current match
        with conn.cursor() as c:
            c.execute("SELECT SUM(amount) FROM payments WHERE tournament_id=%s AND match_number=%s", (t_id, cur_match))
            match_collected = c.fetchone()[0] or 0.0
            
        st.metric(f"Match {cur_match} Progress", f"{match_collected:,.0f} / {target_per_match:,.0f} PKR")
        
        match_progress = float(min(match_collected / target_per_match, 1.0)) if target_per_match > 0 else 0.0
        st.progress(match_progress)
        
        if st.button(f"✅ Mark Match {cur_match} Done & Start Match {cur_match + 1}", use_container_width=True, type="primary"):
            with conn.cursor() as c:
                c.execute("UPDATE tournaments SET current_match = current_match + 1 WHERE id=%s", (t_id,))
            st.toast(f"Advanced to Match {cur_match + 1}!", icon="🚀")
            time.sleep(1)
            st.rerun()

        st.divider()
        st.write("### Transaction History")
        
        if not payments_df.empty:
            display_df = payments_df[['player_name', 'amount', 'match_number', 'date']].copy()
            display_df.columns = ["Player", "Amount (PKR)", "Match #", "Date Recorded"]
            display_df['Date Recorded'] = pd.to_datetime(display_df['Date Recorded']).dt.strftime('%b %d, %I:%M %p')
            
            st.dataframe(display_df, use_container_width=True, hide_index=True)
            
            csv = display_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Excel/CSV", data=csv, file_name=f"{active_t_name.replace(' ', '_').lower()}_payments.csv", mime='text/csv', use_container_width=True, type="primary")
        else:
            st.info("No payments recorded yet.")

    # --- TAB 2: MANAGE PAYMENTS ---
    with tab2:
        players_df = get_players(t_id)
        if players_df.empty:
            st.warning("Add players in the 'Roster' tab first.")
        else:
            st.write(f"### ➕ Log Payment (Defaults to Match {cur_match})")
            with st.form("payment_form", clear_on_submit=True):
                p_dict = dict(zip(players_df.name, players_df.id))
                selected_p = st.selectbox("Player", list(p_dict.keys()))
                amount = st.number_input("Amount (PKR)", min_value=0, step=500)
                # Matches the active match by default!
                match_num = st.number_input("Match #", min_value=1, max_value=int(active_t['total_matches']), value=cur_match, step=1)
                
                if st.form_submit_button("Submit Payment", use_container_width=True, type="primary"):
                    if amount > 0:
                        with conn.cursor() as c:
                            c.execute("INSERT INTO payments (player_id, tournament_id, amount, match_number) VALUES (%s, %s, %s, %s)", 
                                      (int(p_dict[selected_p]), t_id, amount, match_num))
                        st.toast(f"Recorded {amount:,.0f} PKR!", icon="💸")
                        time.sleep(1)
                        st.rerun()
            
            st.divider()
            st.write("### ✏️ Edit Records")
            
            if not payments_df.empty:
                disp_pay = payments_df[['id', 'player_name', 'amount', 'match_number', 'date']].copy()
                disp_pay.columns = ["id", "Player", "Amount", "Match", "Date"]
                
                st.data_editor(
                    disp_pay,
                    column_config={"id": None, "Player": st.column_config.TextColumn(disabled=True), "Date": st.column_config.DatetimeColumn(disabled=True, format="MMM DD")},
                    num_rows="dynamic",
                    key="pay_editor",
                    use_container_width=True
                )
                
                changes = st.session_state.get("pay_editor", {"edited_rows": {}, "deleted_rows": []})
                
                if len(changes["deleted_rows"]) > 0:
                    st.error(f"⚠️ You are about to delete {len(changes['deleted_rows'])} payment(s).")
                    if st.button("🚨 Confirm Deletion", type="primary", use_container_width=True):
                        with conn.cursor() as c:
                            for row_idx in changes["deleted_rows"]:
                                pay_id = int(disp_pay.iloc[row_idx]["id"])
                                c.execute("DELETE FROM payments WHERE id=%s", (pay_id,))
                        st.rerun()
                elif len(changes["edited_rows"]) > 0:
                    if st.button("💾 Save Changes", type="primary", use_container_width=True):
                        with conn.cursor() as c:
                            for row_idx, edit in changes["edited_rows"].items():
                                pay_id = int(disp_pay.iloc[row_idx]["id"])
                                if "Amount" in edit:
                                    c.execute("UPDATE payments SET amount=%s WHERE id=%s", (edit["Amount"], pay_id))
                                if "Match" in edit:
                                    c.execute("UPDATE payments SET match_number=%s WHERE id=%s", (edit["Match"], pay_id))
                        st.toast("Changes saved!", icon="✅")
                        time.sleep(1)
                        st.rerun()
            else:
                st.info("No payments to edit yet.")

    # --- TAB 3: MANAGE ROSTER ---
    with tab3:
        st.write("### ➕ Add Player")
        with st.form("add_player", clear_on_submit=True):
            p_name = st.text_input("Player Name", placeholder="Enter player name...")
            if st.form_submit_button("Add to Roster", use_container_width=True, type="primary"):
                if p_name.strip():
                    with conn.cursor() as c:
                        c.execute("INSERT INTO players (name, tournament_id) VALUES (%s, %s)", (p_name.strip(), t_id))
                    st.toast(f"{p_name} added!", icon="👤")
                    time.sleep(1)
                    st.rerun()

        st.divider()
        st.write("### ✏️ Edit Roster")
        
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
            
            changes = st.session_state.get("roster_editor", {"edited_rows": {}, "deleted_rows": []})
            
            if len(changes["deleted_rows"]) > 0:
                st.error(f"⚠️ You are deleting {len(changes['deleted_rows'])} player(s). This ALSO deletes their payment history!")
                if st.button("🚨 Confirm Deletion", type="primary", use_container_width=True):
                    with conn.cursor() as c:
                        for row_idx in changes["deleted_rows"]:
                            p_id = int(disp_players.iloc[row_idx]["id"])
                            c.execute("DELETE FROM payments WHERE player_id=%s", (p_id,))
                            c.execute("DELETE FROM players WHERE id=%s", (p_id,))
                    st.rerun()
            elif len(changes["edited_rows"]) > 0:
                if st.button("💾 Save Name Changes", type="primary", use_container_width=True):
                    with conn.cursor() as c:
                        for row_idx, edit in changes["edited_rows"].items():
                            if "Player Name" in edit:
                                p_id = int(disp_players.iloc[row_idx]["id"])
                                c.execute("UPDATE players SET name=%s WHERE id=%s", (edit["Player Name"], p_id))
                    st.toast("Roster updated!", icon="✅")
                    time.sleep(1)
                    st.rerun()
        else:
            st.info("No players added yet.")
