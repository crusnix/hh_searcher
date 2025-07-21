import requests
import streamlit as st
from bs4 import BeautifulSoup
import os
import openai
import json
from dotenv import load_dotenv
import time
from urllib.parse import urlencode, unquote_plus

load_dotenv()

# --- Эти функции можно оставить без изменений ---
def get_access_token():
    token = os.getenv("ACCESS_TOKEN")
    if not token:
        st.error("Токен доступа ACCESS_TOKEN не найден в .env файле.")
    return token

def get_current_user_info():
    access_token = get_access_token()
    if not access_token: return None
    headers = {"Authorization": f"Bearer {access_token}", "User-Agent": "ForteTalent/1.3"}
    url = "https://api.hh.ru/me"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    return None

# hh_api_integration_v2.py

@st.cache_data(show_spinner="Загрузка справочника регионов Казахстана...")
def get_area_dictionary():
    """
    Загружает и кэширует справочник регионов ТОЛЬКО для Казахстана.
    Преобразует древовидную структуру в плоский словарь для selectbox.
    """
    try:
        response = requests.get("https://api.hh.ru/areas", timeout=10)
        response.raise_for_status()
        all_countries = response.json()
        
        # 1. Находим объект "Казахстан" в общем списке
        kazakhstan_node = next((country for country in all_countries if country['id'] == '40'), None)

        if not kazakhstan_node:
            st.error("Не удалось найти Казахстан в справочнике регионов HH.ru.")
            return {"Астана": "160", "Алматы": "159"} # Fallback

        area_dict = {}

        def parse_kz_area_node(node):
            """Рекурсивная функция для парсинга регионов внутри Казахстана."""
            # Добавляем в словарь и города, и области
            area_dict[node['name']] = node['id']
            if 'areas' in node and node['areas']:
                for sub_area in node['areas']:
                    parse_kz_area_node(sub_area)

        # 2. Запускаем рекурсивный парсинг только для дочерних регионов Казахстана
        for region in kazakhstan_node['areas']:
            parse_kz_area_node(region)
            
        # 3. Добавляем сам "Казахстан" как опцию для поиска по всей стране
        area_dict[kazakhstan_node['name']] = kazakhstan_node['id']

        # Сортируем словарь по ключам (названиям) для удобства
        return dict(sorted(area_dict.items()))
    
    except requests.exceptions.RequestException as e:
        st.error(f"Не удалось загрузить список регионов: {e}")
        # Возвращаем базовый словарь в случае ошибки
        return {
            "Астана": "160",
            "Алматы": "159",
            "Казахстан": "40"
        }
    
def get_managers(employer_id="24761"):
    access_token = get_access_token()
    if not access_token: return []
    headers = {"Authorization": f"Bearer {access_token}", "User-Agent": "ForteTalent/1.3"}
    url = f"https://api.hh.ru/employers/{employer_id}/managers"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get('items', [])
    return []

def get_active_vacancies(manager_ids, employer_id="24761"):
    access_token = get_access_token()
    if not access_token: return []
    headers = {"Authorization": f"Bearer {access_token}", "User-Agent": "ForteTalent/1.3"}
    all_vacancies = []
    for manager_id in manager_ids:
        url = f"https://api.hh.ru/employers/{employer_id}/vacancies/active"
        params = {"page": 0, "per_page": 50, "manager_id": manager_id}
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            all_vacancies.extend(response.json().get('items', []))
    return all_vacancies

def get_vacancy_details(vacancy_id):
    url = f"https://api.hh.ru/vacancies/{vacancy_id}"
    headers = {"User-Agent": "ForteTalent/1.3"}
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt < 2: time.sleep(2)
            else: st.error(f"Не удалось получить детали вакансии: {e}")
    return None

# --- ИЗМЕНЕНИЕ: Функции для OpenAI и Поиска ---

@st.cache_data(show_spinner="Анализ вакансии с помощью AI...")
# hh_api_integration_v2.py

@st.cache_data(show_spinner="Анализ вакансии с помощью AI...")
def generate_keywords_with_openai(vacancy_name, vacancy_description_html):
    """
    Вызывает OpenAI ОДИН РАЗ на вакансию (благодаря кэшу Streamlit),
    чтобы сгенерировать максимально полный набор ключевых слов.
    Принимает только необходимые, неизменяемые части для кэширования.
    """
    openai.api_key = os.getenv("OPENAI_API_KEY")
    if not openai.api_key:
        st.error("Ключ OPENAI_API_KEY не найден.")
        return None

    # ИСПРАВЛЕНИЕ: работаем с переданными аргументами, а не со словарем
    soup = BeautifulSoup(vacancy_description_html, 'html.parser')
    vacancy_text = f"Название: {vacancy_name}\n\nОписание:\n{soup.get_text(separator=' ')}"
    
    system_prompt = """
    Ты — эксперт-рекрутер. Проанализируй вакансию и верни JSON-объект.
    ЗАДАЧА: Максимально полно и релевантно заполни ВСЕ поля в JSON-структуре, фокусируясь ТОЛЬКО на профессиональных компетенциях.
    ИНСТРУКЦИИ:
    - Используй короткие, атомарные термины (1-2 слова). 'Oracle' вместо 'Опыт работы с Oracle'.
    - 'must_have': ТОЛЬКО самые критичные технологии/навыки.
    - 'technologies': Другие важные, но более гибкие технологии.
    - 'domain': Отраслевые термины (финтех, AML, скоринг).
    - 'job_titles': Синонимы и альтернативные названия должности.
    - 'negative_keywords': Кого ТОЧНО не ищем (Junior, Стажер, QA).
    
    ЗАПРЕЩЕНО: НЕ включай в ключевые слова требования к образованию, опыту работы (годы) или знанию языков. Для этого есть отдельные фильтры.

    Структура JSON:
    {{
      "must_have": [],
      "technologies": [],
      "domain": [],
      "job_titles": [],
      "negative_keywords": []
    }}
    ВЕРНИ ТОЛЬКО JSON.
    """
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Вакансия:\n{vacancy_text}"}
            ],
            response_format={"type": "json_object"}, temperature=0.1)
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        st.error(f"Ошибка при обращении к OpenAI API: {e}")
        return None
    
    
def advanced_search_resumes_old(structured_keywords, search_filters, mode="Средний"):
    access_token = get_access_token()
    if not access_token: return None
    headers = {"Authorization": f"Bearer {access_token}", "User-Agent": "ForteTalent/1.3"}

    def format_keyword(kw):
        kw = kw.strip()
        if not kw: return None
        if '/' in kw: return f"({' AND '.join(kw.split('/'))})"
        if ' ' in kw: return f'"{kw}"'
        return kw

    def build_main_query_text(kw, query_mode):
        def format_list(keywords):
            return [f for k in keywords if (f := format_keyword(k))]

        must_have = format_list(kw.get("must_have", []))
        technologies = format_list(kw.get("technologies", []))
        domain = format_list(kw.get("domain", []))
        negative = format_list(kw.get("negative_keywords", []))

        query_parts = []
        if query_mode == "Строгий":
            if must_have: query_parts.append(f"({' AND '.join(must_have)})")
            if technologies: query_parts.append(f"({' OR '.join(technologies)})")
            if domain: query_parts.append(f"({' OR '.join(domain)})")
        
        elif query_mode == "Средний":
            if must_have: query_parts.append(f"({' AND '.join(must_have)})")
            combined_or = technologies + domain
            if combined_or: query_parts.append(f"({' OR '.join(combined_or)})")

        else:  # Обширный
            all_keywords = must_have + technologies + domain
            if all_keywords: query_parts.append(f"({' OR '.join(all_keywords)})")
        
        if negative:
            query_parts.append(f"NOT ({' OR '.join(negative)})")
        
        return " AND ".join(filter(None, query_parts))

    strategies = []
    kw = structured_keywords
    main_query_text = build_main_query_text(kw, mode)
    if main_query_text:
        strategies.append({"name": f"Main Search ({mode})", "params": {"text": main_query_text}, "score": 10})

    found_resumes = {}
    base_url = "https://api.hh.ru/resumes"
    print("\n--- DEBUG: ГЕНЕРАЦИЯ ПОИСКОВЫХ ЗАПРОСОВ ---")
    with st.spinner(f"Выполняю поиск в режиме '{mode}'..."):
        for strategy in strategies:
            current_params = {**search_filters, **strategy["params"]}
            query_string = urlencode(current_params, doseq=True)
            human_readable_url = unquote_plus(f"{base_url}?{query_string}")
            print(f"[*] Стратегия '{strategy['name']}':\n    {human_readable_url}\n")
            
            try:
                response = requests.get(base_url, headers=headers, params=current_params, timeout=15)
                response.raise_for_status()
                data = response.json()
                for resume in data.get("items", []):
                    resume_id = resume["id"]
                    if resume_id not in found_resumes:
                        found_resumes[resume_id] = {"data": resume, "score": 0}
                    found_resumes[resume_id]["score"] += strategy["score"]
            except requests.exceptions.RequestException as e:
                st.warning(f"Ошибка при поиске по стратегии '{strategy['name']}': {e}")
    if not found_resumes: return {"found": 0, "items": []}
    return {"found": len(found_resumes), "items": sorted(list(found_resumes.values()), key=lambda x: x["score"], reverse=True)}

# hh_api_integration_v2.py

def advanced_search_resumes(structured_keywords, search_filters, mode="Средний"):
    access_token = get_access_token()
    if not access_token: return None
    headers = {"Authorization": f"Bearer {access_token}", "User-Agent": "ForteTalent/1.5"}

    def format_keyword(kw):
        kw = kw.strip()
        if not kw: return None
        if '/' in kw: return f"({' AND '.join(kw.split('/'))})"
        if ' ' in kw: return f'"{kw}"'
        return kw

    def build_main_query_text(kw, query_mode, user_job_title=None, bank_only=False):
        def format_list(keywords):
            return [f for k in keywords if (f := format_keyword(k))]

        must_have = format_list(kw.get("must_have", []))
        technologies = format_list(kw.get("technologies", []))
        domain = format_list(kw.get("domain", []))
        negative = format_list(kw.get("negative_keywords", []))

        query_parts = []

        # --- ИЗМЕНЕНИЕ: Сначала добавляем жесткие фильтры от пользователя ---
        if user_job_title:
            query_parts.append(format_keyword(user_job_title))
        if bank_only:
            query_parts.append("банк")

        # --- Затем добавляем гибкую логику по ключевым словам в зависимости от режима ---
        ai_parts = []
        if query_mode == "Строгий":
            if must_have: ai_parts.append(f"({' AND '.join(must_have)})")
            if technologies: ai_parts.append(f"({' OR '.join(technologies)})")
            if domain: ai_parts.append(f"({' OR '.join(domain)})")
        elif query_mode == "Средний":
            if must_have: ai_parts.append(f"({' AND '.join(must_have)})")
            combined_or = technologies + domain
            if combined_or: ai_parts.append(f"({' OR '.join(combined_or)})")
        else:  # Обширный
            all_keywords = must_have + technologies + domain
            if all_keywords: ai_parts.append(f"({' OR '.join(all_keywords)})")

        if ai_parts:
            # Объединяем AI-части в одну группу в скобках, чтобы они не конфликтовали с жесткими фильтрами
            query_parts.append(f"({' AND '.join(ai_parts)})")
        
        # Минус-слова всегда в конце
        if negative:
            query_parts.append(f"NOT ({' OR '.join(negative)})")
        
        return " AND ".join(filter(None, query_parts))

    # --- ИЗМЕНЕНИЕ: Извлекаем новые фильтры перед API вызовом ---
    # Мы извлекаем их, чтобы они не попали в `params` напрямую, т.к. они влияют на поле `text`
    user_job_title = search_filters.pop("user_job_title", None)
    bank_only = search_filters.pop("bank_only", False)
    
    # Теперь `search_filters` содержит только "чистые" API-параметры (area, language, etc.)

    strategies = []
    kw = structured_keywords
    main_query_text = build_main_query_text(kw, mode, user_job_title, bank_only)
    
    if main_query_text:
        strategies.append({"name": f"Main Search ({mode})", "params": {"text": main_query_text}, "score": 10})

    found_resumes = {}
    base_url = "https://api.hh.ru/resumes"
    print("\n--- DEBUG: ГЕНЕРАЦИЯ ПОИСКОВЫХ ЗАПРОСОВ ---")
    with st.spinner(f"Выполняю поиск в режиме '{mode}'..."):
        for strategy in strategies:
            # `search_filters` уже не содержит наши кастомные поля
            current_params = {**search_filters, **strategy["params"]}
            query_string = urlencode(current_params, doseq=True)
            human_readable_url = unquote_plus(f"{base_url}?{query_string}")
            print(f"[*] Стратегия '{strategy['name']}':\n    {human_readable_url}\n")
            
            try:
                response = requests.get(base_url, headers=headers, params=current_params, timeout=15)
                response.raise_for_status()
                data = response.json()
                for resume in data.get("items", []):
                    resume_id = resume["id"]
                    if resume_id not in found_resumes:
                        found_resumes[resume_id] = {"data": resume, "score": 0}
                    found_resumes[resume_id]["score"] += strategy["score"]
            except requests.exceptions.RequestException as e:
                st.warning(f"Ошибка при поиске по стратегии '{strategy['name']}': {e}")
    
    if not found_resumes: return {"found": 0, "items": []}
    return {"found": len(found_resumes), "items": sorted(list(found_resumes.values()), key=lambda x: x["score"], reverse=True)}