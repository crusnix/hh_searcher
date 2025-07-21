import streamlit as st
from datetime import datetime
import hh_api_integration_v2 as hh
from bs4 import BeautifulSoup

# --- Конфигурация страницы и Стили (сохранены из вашей версии) ---
st.set_page_config(
    page_title="ForteTalent",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    /* ... (Ваши стили остаются без изменений) ... */
    .vacancy-card {
        background-color: #FFFFFF; border: 1px solid #E0E1DD; border-radius: 12px;
        padding: 20px; margin-bottom: 1rem; box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        transition: transform 0.2s, box-shadow 0.2s;
        height: 200px; /* Немного увеличим высоту для города */
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    .vacancy-card:hover { transform: translateY(-5px); box-shadow: 0 8px 20px rgba(0,0,0,0.08); }
    .vacancy-title { font-size: 1.1rem; font-weight: bold; color: #1B263B; margin-bottom: 0.5rem; }
    .sub-header { font-size: 1.8rem; font-weight: bold; color: #1B263B; margin-top: 2rem; margin-bottom: 1rem; border-bottom: 3px solid #415A77; padding-bottom: 0.5rem;}
    .section-header { font-size: 1.4rem; font-weight: bold; color: #1B263B; margin-top: 1.5rem; margin-bottom: 1rem; }
    .stButton>button { border-radius: 8px; border: 1px solid #415A77; background-color: #415A77; color: white; padding: 0.5rem 1.25rem; font-weight: 600; }
    .stButton>button:hover { background-color: #1B263B; border-color: #1B263B; color: white; }
    mark { background-color: #FFF9C4; padding: 0.2em; border-radius: 3px;}
</style>
""", unsafe_allow_html=True)

# --- Инициализация Session State ---
def init_session_state():
    defaults = {
        'hh_selected_vacancy_id': None,
        'structured_keywords': None,
        'current_user': None,
        'hh_active_vacancies': []
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# --- Функции-помощники ---
def fetch_initial_data():
    if st.session_state.current_user is None:
        st.session_state.current_user = hh.get_current_user_info()
    if not st.session_state.hh_active_vacancies and hh.get_access_token():
        with st.spinner("Загрузка активных вакансий..."):
            managers = hh.get_managers()
            if managers:
                st.session_state.hh_active_vacancies = hh.get_active_vacancies([m['id'] for m in managers])

def highlight_snippet(text):
    if not text: return ""
    return text.replace('<highlighttext>', '<mark>').replace('</highlighttext>', '</mark>')

# --- UI Компоненты ---
def display_vacancy_card(vacancy):
    with st.container(border=True):
        city = vacancy.get('area', {}).get('name', 'Город не указан')
        st.markdown(f'<div class="vacancy-card"><div>'
                    f'<p class="vacancy-title">{vacancy["name"]}</p>'
                    f'<span style="color: #778DA9; font-size: 0.9em;">📍 {city}</span>'
                    f'</div>', unsafe_allow_html=True)
        if st.button("Найти кандидатов", key=f"process_hh_{vacancy['id']}", use_container_width=True):
            st.session_state.hh_selected_vacancy_id = vacancy['id']
            st.session_state.structured_keywords = None
            if 'hh_search_results' in st.session_state: del st.session_state.hh_search_results
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

def render_home_page():
    if st.session_state.current_user:
        user = st.session_state.current_user
        st.markdown(f"### Добро пожаловать, {user.get('first_name', '')} {user.get('last_name', '')}!")
    st.markdown('<div class="sub-header">Активные вакансии</div>', unsafe_allow_html=True)
    if st.button("🔄 Обновить список"):
        st.session_state.hh_active_vacancies = []
        fetch_initial_data()
        st.rerun()

    # ИЗМЕНЕНИЕ: Разделение вакансий на "мои" и "все остальные"
    my_vacancies = []
    other_vacancies = []
    user_id = st.session_state.current_user.get('id') if st.session_state.current_user else None
    
    if user_id:
        for v in st.session_state.hh_active_vacancies:
            if v.get('manager', {}).get('id') == user_id:
                my_vacancies.append(v)
            else:
                other_vacancies.append(v)
    else:
        other_vacancies = st.session_state.hh_active_vacancies

    # Отображение "Мои вакансии"
    st.markdown('<div class="section-header">Мои вакансии</div>', unsafe_allow_html=True)
    if my_vacancies:
        cols = st.columns(3)
        for i, vacancy in enumerate(my_vacancies):
            with cols[i % 3]:
                display_vacancy_card(vacancy)
    else:
        st.info("У вас нет персонально назначенных активных вакансий.")

    # Отображение "Все остальные вакансии"
    st.markdown('<div class="section-header">Все остальные вакансии</div>', unsafe_allow_html=True)
    if other_vacancies:
        cols = st.columns(3)
        for i, vacancy in enumerate(other_vacancies):
            with cols[i % 3]:
                display_vacancy_card(vacancy)
    elif not my_vacancies:
        st.warning("Не найдено активных вакансий в компании.")


def render_keyword_extraction_page():
    vacancy_id = st.session_state.hh_selected_vacancy_id
    vacancy_details = hh.get_vacancy_details(vacancy_id)
    if not vacancy_details:
        st.error("Не удалось загрузить детали вакансии.")
        if st.button("⬅️ Назад"): st.session_state.hh_selected_vacancy_id = None; st.rerun()
        return

    st.markdown('<div class="sub-header">Поиск по вакансии</div>', unsafe_allow_html=True)
    if st.button("⬅️ Вернуться к списку вакансий"):
        st.session_state.hh_selected_vacancy_id = None; st.rerun()

    # ИЗМЕНЕНИЕ: Название вакансии и опыт на отдельных строках
    st.markdown(f"## {vacancy_details.get('name')}")
    st.caption(f"Требуемый опыт: **{vacancy_details.get('experience', {}).get('name', 'Не указан')}**")

    with st.expander("Показать/скрыть описание вакансии"):
        soup = BeautifulSoup(vacancy_details.get('description', ''), 'html.parser')
        st.markdown(soup.prettify(), unsafe_allow_html=True)

    if st.session_state.structured_keywords is None:
        st.session_state.structured_keywords = hh.generate_keywords_with_openai(
            vacancy_details.get("name", ""), vacancy_details.get("description", ""))
    
    keywords = st.session_state.structured_keywords
    if not keywords:
        st.error("Не удалось сгенерировать ключевые слова."); return

    st.markdown("#### Шаг 1: Ключевые слова для поиска")
    with st.container(border=True):
        st.info("Вы можете отредактировать список слов (разделяйте запятой)")
        keywords['must_have'] = st.text_input("Обязательные (AND)", ", ".join(keywords.get('must_have', [])), key=f"must_{vacancy_id}").split(',')
        keywords['technologies'] = st.text_input("Технологии (OR)", ", ".join(keywords.get('technologies', [])), key=f"tech_{vacancy_id}").split(',')
        keywords['domain'] = st.text_input("Сфера/Домен (OR)", ", ".join(keywords.get('domain', [])), key=f"domain_{vacancy_id}").split(',')
        keywords['negative_keywords'] = st.text_input("Минус-слова (NOT)", ", ".join(keywords.get('negative_keywords', [])), key=f"neg_{vacancy_id}").split(',')
        for k in keywords: keywords[k] = [item.strip() for item in keywords[k] if item.strip()]
        st.session_state.structured_keywords = keywords

    st.markdown("#### Шаг 2: Режим поиска и фильтры")
    search_mode = st.radio("Режим поиска:", ["Строгий", "Средний", "Обширный"], index=1, horizontal=True)

    kz_areas_dict = hh.get_area_dictionary()
    area_options = list(kz_areas_dict.keys())

    # 2. Определяем регион по умолчанию из вакансии
    default_area_name = vacancy_details.get('area', {}).get('name', 'Астана')
    default_index = area_options.index(default_area_name) if default_area_name in area_options else 0
    
    # 3. Создаем фильтры в колонках
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("##### **Точные критерии**")
        user_job_title = st.text_input("Название должности (точное совпадение):")
        bank_only = st.checkbox("Искать только с опытом работы в банке")
        
        st.markdown("##### **Статус и занятость**")
        job_search_status = st.multiselect("Статус поиска:",
            options=['active_search', 'looking_for_offers', 'has_job_offer'], default=['active_search', 'looking_for_offers'],
            format_func=lambda x: {'active_search': 'Активный', 'looking_for_offers': 'Рассматривает', 'has_job_offer': 'Есть оффер'}.get(x, x))
    
    with col2:
        st.markdown("##### **Квалификация**")
        experience = st.multiselect("Опыт работы:",
            options=["noExperience", "between1And3", "between3And6", "moreThan6"], default=["between3And6"],
            format_func=lambda x: {"noExperience": "Нет", "between1And3": "1-3", "between3And6": "3-6", "moreThan6": "6+"}.get(x, x))
        
        education_levels = st.multiselect("Образование:",
            options=['higher', 'bachelor', 'master', 'special_secondary', 'secondary', 'unfinished_higher', 'candidate', 'doctor'], default=['higher', 'bachelor'],
            format_func=lambda x: {'higher': 'Высшее', 'bachelor': 'Бакалавр', 'master': 'Магистр', 'special_secondary': 'Среднее спец.', 'secondary' : 'Среднее',
                                   'unfinished_higher':'Неоконченное высшее','candidate':'Кандидат наук','doctor':'Доктор наук'}.get(x,x))
        
        # Новый фильтр по языкам
        languages = st.multiselect("Знание языков:",
            options=['rus', 'kaz', 'eng'], default=[],
            format_func=lambda x: {'rus': 'Русский', 'kaz': 'Казахский', 'eng': 'Английский'}.get(x,x))


    if st.button("🚀 Найти кандидатов", use_container_width=True, type="primary"):
        search_filters = {
            "area": vacancy_details.get('area', {}).get('id', '160'),
            "employment": ["full"],
            "experience": experience,
            "job_search_status": job_search_status,
            "education_levels": education_levels,
            "language": languages, # Добавляем языки
            "per_page": 20,
            # Добавляем кастомные поля для передачи в query builder
            "user_job_title": user_job_title,
            "bank_only": bank_only,
        }
        st.session_state.hh_search_results = hh.advanced_search_resumes(keywords, search_filters, search_mode)

    if 'hh_search_results' in st.session_state and st.session_state.hh_search_results:
        results = st.session_state.hh_search_results
        st.markdown(f'<div class="section-header">Найдено резюме: {results.get("found", 0)}</div>', unsafe_allow_html=True)
        for item in results.get('items', []):
            resume = item.get("data", {})
            score = item.get("score", 0)
            with st.container(border=True):
                col_r1, col_r2 = st.columns([4, 1])
                with col_r1:
                    st.markdown(f"**{resume.get('title', 'Без названия')}**")
                    last_job = (resume.get('experience') or [{}])[0]
                    st.markdown(f"🏢 {last_job.get('company', 'Место работы не указано')} — **{last_job.get('position', 'Должность не указана')}**")
                    st.caption(f"Возраст: {resume.get('age', 'N/A')}")
                    snippet_html = resume.get('snippet', {}).get('requirement', '') or resume.get('snippet', {}).get('responsibility', '')
                    if snippet_html: st.markdown(f"<div style='font-size:0.9em;margin-top:8px;'>{highlight_snippet(snippet_html)}</div>", unsafe_allow_html=True)
                with col_r2:
                    #st.markdown(f"<div style='text-align:right;'><span class='stBadge'>Балл: {score}</span></div>", unsafe_allow_html=True)
                    st.link_button("🔗 на HH.ru", resume.get('alternate_url', '#'), use_container_width=True)



# --- Основное приложение ---
def main():
    with st.sidebar:
       st.markdown('<h1 class="sidebar-header">ForteTalent</h1>', unsafe_allow_html=True)
       st.markdown("---")
       page_options = ["Поиск HH", "Сопоставление", "База данных", "Отклики"]
       
       st.session_state.app_page = st.radio("Навигация:", page_options)
       st.markdown("---")
    fetch_initial_data()
    
    if st.session_state.hh_selected_vacancy_id:
        render_keyword_extraction_page()
    else:
        render_home_page()

if __name__ == "__main__":
    main()

