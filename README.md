# J.A.R.V.İ.S — Türkçe Sesli Sınıf Asistanı

Akıllı tahta ve bilgisayar için Türkçe konuşan bir sesli asistan. Ona sesle ya da yazıyla soru sorarsınız, Türkçe sesle yanıt verir; YouTube'da video açar, ders kitabını açar, sayfayı kaydırır, kurulu uygulamaları başlatır, ekrana bakıp tıklayarak çok adımlı işleri kendisi yapar ve notlarınızı 3B bir "bilgi galaksisi"nde gösterir.

> **Bilgisayarda hiçbir yapay zekâ modeli çalışmaz.** Tüm zekâ bulut API'lerinden gelir:
> düşünme **Groq** (gpt-oss-120b), dinleme **Groq Whisper**, konuşma ve görme **Google Gemini**.

---

## İçindekiler

1. [Özellikler](#özellikler)
2. [Gerekenler](#gerekenler)
3. [Kurulum — Linux / Pardus](#kurulum--linux--pardus)
4. [Kurulum — Windows 11](#kurulum--windows-11)
5. [API anahtarlarını almak](#api-anahtarlarını-almak)
6. [İlk çalıştırma](#ilk-çalıştırma)
7. [Sesli komutlar](#sesli-komutlar)
8. [Notlar ve bilgi galaksisi](#notlar-ve-bilgi-galaksisi)
9. [Ders kitapları](#ders-kitapları)
10. [Ayarlar](#ayarlar)
11. [Sistem kontrolü (preflight)](#sistem-kontrolü-preflight)
12. [Sorun giderme](#sorun-giderme)
13. [Güvenlik ve gizlilik](#güvenlik-ve-gizlilik)
14. [Proje yapısı](#proje-yapısı)

---

## Özellikler

### 🎙️ Sesli konuşma
- **"Hey Jarvis"** ya da **"Tahta"** diye seslendiğinizde uyanır; tarayıcı küçültülmüş ya da arkada olsa bile Jarvis penceresi öne gelir ve "Dinliyorum, Hocam." der.
- Konuşmanızı **Groq Whisper** yazıya çevirir, yanıtı **Gemini** doğal bir Türkçe sesle okur.
- Konuşma geçmişini hatırlar; "Yeni sohbet" ile sıfırlanır.

### 🧠 Düşünme (beyin)
- Varsayılan beyin: **Groq `openai/gpt-oss-120b`** (ücretsiz, çok hızlı — yanıtlar genelde 1 saniyenin altında).
- Bir modelin ücretsiz sınırı dolarsa Jarvis otomatik olarak **`qwen/qwen3.8-27b`**, sonra **`openai/gpt-oss-20b`** modeline geçer.
- Ayarlardan **Gemini**, **Hugging Face (Gemma 2 9B)** ya da **Abacus.AI** da seçilebilir.

### 🖥️ Bilgisayar kontrolü
- **YouTube:** "YouTube'da fotosentez videosu aç" → arar ve ilk videoyu oynatır.
- **Uygulama açma:** "FlowingTR'yi aç", "hesap makinesini aç", "LibreOffice Writer'ı aç" — bilgisayarda kurulu her uygulamayı adıyla bulur.
- **Çok adımlı görevler (görsel ajan):** "YouTube'da Evrim Ağacı kanalını bul ve son videoyu aç" gibi isteklerde adımları kendisi planlar; ekran görüntüsünü Gemini'ye gösterip düğmenin yerini bulur, fareyi bir insan gibi hareket ettirip tıklar, yazar, kaydırır (en fazla 12 adım).
- **Ekran:** "aşağı kaydır", "biraz yukarı", "ortaya tıkla".
- Her eylemden sonra Jarvis yalnızca **gerçekten yapılanı** söyler (makbuz sistemi); yapamadıysa nedenini söyler.

### 📚 Öğretmen araçları
- **Ders kitabı:** "Matematik kitabını aç" → `textbooks/` klasöründeki dosyayı ya da kayıtlı web adresini açar.
- **Hafıza:** "Hatırla: yarın 10-B'nin sınavı var" → not olarak saklar, sonra sorduğunuzda bulur. "Hafıza" çekmecesinden listelenir ve silinir.
- **Bilgi galaksisi:** `notes/` klasöründeki notlarınız 3B bir galaksi olarak görünür; sorularınıza notlarınızdan kaynak göstererek yanıt verir.

### 🛠️ Proje mimarı
- Bir proje fikrini Jarvis'le konuşarak geliştirin; **"Bunu koda dök"** deyince konuşmayı ayrıntılı bir İngilizce prompta çevirir ve Claude masaüstü uygulamasına yapıştırır (ya da Abacus.AI ajanına yazdırır).

---

## Gerekenler

| Gereken | Açıklama |
|---|---|
| **Python 3.10 veya üstü** | Pardus/Debian'da genelde kuruludur: `python3 --version` |
| **Google Chrome** | Mikrofon ve arayüz için önerilir |
| **Mikrofon + hoparlör** | Sesli kullanım için |
| **İnternet** | Tüm yapay zekâ bulutta çalışır |
| **Groq API anahtarı** | Ücretsiz — dinleme ve düşünme için **zorunlu** |
| **Gemini API anahtarı** | Ücretsiz — Jarvis'in sesi ve görmesi için **zorunlu** |

---

## Kurulum — Linux / Pardus

### 1. Sistem paketleri

Terminali açın (`Ctrl+Alt+T`) ve şunu çalıştırın (yönetici şifresi ister):

```bash
sudo apt install python3-venv python3-pip git xclip wmctrl xdotool libportaudio2 zenity curl
```

| Paket | Ne için |
|---|---|
| `python3-venv`, `python3-pip` | Python paketlerini kurmak |
| `xclip` | Türkçe karakterleri (ç, ğ, ş…) yazabilmek |
| `wmctrl`, `xdotool` | Jarvis penceresini öne getirmek |
| `libportaudio2` | "Hey Jarvis" için mikrofonu dinlemek |
| `zenity`, `curl` | Başlatma betiğinin uyarı pencereleri ve kontrolleri |

> Pardus'ta oturumun **X11** (Xorg) olması gerekir; fare/klavye kontrolü Wayland'de çalışmaz.

### 2. Projeyi indirin

```bash
cd ~/Masaüstü && git clone https://github.com/Eren0764/Erunal-jarvis.git JARVİS
```

### 3. Başlatın

```bash
cd ~/Masaüstü/JARVİS && ./jarvis-baslat.sh
```

İlk çalıştırmada betik `.venv` klasörünü oluşturup gerekli Python paketlerini kurar (**1–2 dakika** sürer). Sonra sunucuyu ve "Hey Jarvis" servisini arka planda başlatır ve Chrome'da **http://127.0.0.1:4700** adresini açar.

Kapatmak için:

```bash
cd ~/Masaüstü/JARVİS && ./jarvis-durdur.sh
```

> İsterseniz masaüstüne bir kısayol (`.desktop` dosyası) oluşturup `jarvis-baslat.sh` dosyasını çift tıklamayla çalıştırabilirsiniz.

---

## Kurulum — Windows 11

1. **Python'u kurun:** [python.org/downloads](https://www.python.org/downloads/) → kurulumun ilk ekranında **"Add python.exe to PATH"** kutusunu işaretleyin.
2. **Projeyi indirin:** GitHub sayfasında yeşil **Code → Download ZIP** düğmesine basın ve ZIP'i bir klasöre çıkarın.
3. **Başlatın:** klasördeki **`jarvis-baslat.bat`** dosyasına çift tıklayın. İlk seferde paketler kurulur, sonra tarayıcıda Jarvis açılır. "Hey Jarvis" servisi bildirim alanında (saatin yanında) simge olarak çalışır.
4. **Kapatmak için:** `jarvis-durdur.bat`.

> Windows tarafı Linux kadar test edilmedi; bir sorun görürseniz `data\sunucu.log` dosyasına bakın.

---

## API anahtarlarını almak

Üçü de **ücretsizdir**. Anahtarları kimseyle paylaşmayın.

### Groq (zorunlu — dinleme + düşünme)
1. [console.groq.com/keys](https://console.groq.com/keys) adresine gidin, Google hesabınızla giriş yapın.
2. **Create API Key** → bir ad verin → `gsk_…` ile başlayan anahtarı kopyalayın.

### Gemini (zorunlu — ses + görme)
1. [aistudio.google.com/apikey](https://aistudio.google.com/apikey) adresine gidin.
2. **Create API key** → `AIza…` anahtarını kopyalayın.
3. **İpucu:** ücretsiz kota düşüktür. Farklı Google hesaplarından birkaç anahtar alıp hepsini eklerseniz, biri dolunca Jarvis otomatik olarak sıradakine geçer.

### Hugging Face (isteğe bağlı)
Yalnızca beyin olarak "Hugging Face (Gemma 2 9B)" seçmek isterseniz gerekir. **Not:** Hugging Face'in ücretsiz hesaplarında aylık kredi yoktur; kredi satın almadan çalışmaz.

---

## İlk çalıştırma

1. Jarvis açılınca sağ üstteki **⚙ (Ayarlar)** düğmesine basın.
2. **Gemini API anahtarları** kutusuna anahtar(lar)ınızı yapıştırın — her satıra bir tane.
3. **Groq API anahtarı** kutusuna `gsk_…` anahtarınızı yapıştırın.
4. **Kaydet**'e basın. Jarvis anahtarları dener ve "Anahtar hazır" der.
5. Sayfaya bir kez **tıklayın** (tarayıcılar, sayfaya tıklanmadan ses çalmaya izin vermez).
6. Mikrofon izni sorulursa **İzin ver** deyin.
7. **"Hey Jarvis"** deyin, "Dinliyorum, Hocam." yanıtını bekleyin, sonra sorunuzu sorun.

Anahtarlar proje klasöründeki **`config.json`** dosyasına kaydedilir. Bu dosya tarayıcıdan okunamaz ve GitHub'a yüklenmez.

---

## Sesli komutlar

Her komutun başına "Hey Jarvis" ya da "Tahta" diyebilirsiniz.

| Ne yapar | Örnek |
|---|---|
| Soru sorma | "Fotosentez nedir, kısaca anlatır mısın?" |
| YouTube videosu | "YouTube'da hücre bölünmesi videosu aç" |
| Çok adımlı görev | "YouTube'da Evrim Ağacı kanalını bul ve son videoyu aç" |
| Uygulama açma | "FlowingTR'yi aç", "Hesap makinesini aç", "Chrome'u aç ve wikipedia.org'a git" |
| Ders kitabı | "Matematik kitabını aç" |
| Kaydırma | "Aşağı kaydır", "Biraz yukarı", "En aşağı in" |
| Tıklama | "Ortaya tıkla" (ör. videoyu durdurmak için) |
| Hatırlama | "Hatırla: Cuma günü veli toplantısı var" |
| Hafızadan silme | "Veli toplantısı notunu sil" |
| Hafızayı sıfırlama | "Hafızayı sıfırla" → "Evet sıfırla" |
| Durdurma | "İptal", "Vazgeç" (çalışan çok adımlı görevi durdurur) |
| Koda dökme | "Bunu koda dök", "Projeyi onayla" |

---

## Notlar ve bilgi galaksisi

- Kendi notlarınızı **Markdown (`.md`)** dosyaları olarak `notes/` klasörüne koyun. Alt klasörler ders/konu grupları olur.
- Notlar arasında bağlantı kurmak için `[[Not Adı]]` yazın.
- Notları ekledikten sonra galaksiyi yenileyin:

```bash
cd ~/Masaüstü/JARVİS && .venv/bin/python build.py
```

- Galaksi arayüzde **"Bilgi Galaksisi"** düğmesinden açılır. Jarvis, sorularınızı yanıtlarken ilgili notları kullanır ve hangi notlardan yararlandığını gösterir.

---

## Ders kitapları

- PDF, EPUB ya da HTML kitapları **`textbooks/`** klasörüne koyun. **Dosya adı = ders adı** olsun: `matematik.pdf`, `fizik.pdf`, `tarih.epub`.
- Web adresindeki kitaplar için `config.json`'a ekleyin:

```json
"textbooks": {"biyoloji": "https://...", "edebiyat": "textbooks/edebiyat-11.pdf"}
```

- Sesli komut: **"Biyoloji kitabını aç"**.

---

## Ayarlar

⚙ penceresinden:

| Ayar | Açıklama |
|---|---|
| Gemini API anahtarları | Ses ve görme için; birden çok anahtar sırayla kullanılır |
| Groq API anahtarı | Dinleme ve (varsayılan) düşünme için |
| Hugging Face API anahtarı | Yalnızca Gemma 2 seçilirse |
| Gemini modeli | Ses/görme için model (varsayılan `gemini-3.8-flash`) |
| Sohbet için yapay zekâ | **Groq** (önerilen), Hugging Face, Gemini, Abacus.AI |
| "Bunu koda dök" deyince | Promptu Claude uygulamasına yapıştır / Abacus ajanı yazsın |

`config.json` içinde elle düzenlenebilen ek ayarlar:

| Anahtar | Anlamı |
|---|---|
| `vision_model` | Görsel ajan için ayrı bir Gemini modeli |
| `huggingface_max_new_tokens` | Hugging Face yanıt uzunluğu (varsayılan 256) |
| `computer_use_waits` | Çok adımlı görevlerde adımlar arası bekleme süreleri (saniye) |
| `textbooks` | Ders adı → dosya/web adresi |

---

## Sistem kontrolü (preflight)

Her şeyin çalışıp çalışmadığını tek komutla kontrol edin (Jarvis açıkken):

```bash
cd ~/Masaüstü/JARVİS && .venv/bin/python preflight.py
```

Sunucu, anahtarlar, Groq beyni, Gemini sesi ve görmesi, mikrofon/uyandırma, fare kontrolü (deneme modunda — fare gerçekten oynamaz) ve daha fazlası tek tek denenir. Sonunda şöyle bir özet çıkar:

```
22 pass, 0 fail, 1 warn
```

`✘` olan satırlar neyin bozuk olduğunu Türkçe açıklar.

---

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| "Kota doldu (429)" | Gemini'nin ücretsiz günlük kotası bitti. Ertesi günü bekleyin ya da ⚙'den başka hesaplardan Gemini anahtarı ekleyin. |
| Jarvis konuşmuyor (ses yok) | Sayfaya bir kez tıklayın; Gemini kotasını kontrol edin. |
| "Hey Jarvis" duyulmuyor | `data/daemon.log` dosyasına bakın. Mikrofon listesi: `.venv/bin/python daemon.py --list-devices` |
| "4700 portunu başka program kullanıyor" | `./jarvis-durdur.sh` çalıştırın, sonra tekrar başlatın. |
| Uygulama açılmıyor | "… adında kurulu bir uygulama bulamadım" diyorsa adı menüdeki gibi söyleyin. Terminal ve Ayarlar güvenlik nedeniyle sesle açılmaz. |
| YouTube açılmıyor | Okul (MEB) ağı YouTube'u engelliyor olabilir; Jarvis bunu söyler. |
| SSL / sertifika hatası | Okul ağı HTTPS trafiğini yeniden imzalar; Jarvis işletim sisteminin sertifika deposunu kullanır. Sorun sürerse `ca-certificates` paketinin güncel olduğundan emin olun. |
| Başka bir hata | `data/sunucu.log` dosyasının son satırlarına bakın, sonra `preflight.py` çalıştırın. |

---

## Güvenlik ve gizlilik

- **API anahtarları** yalnızca `config.json`'da durur; tarayıcıya sunulmaz, günlüklere yazılmaz, `.gitignore` sayesinde GitHub'a yüklenmez.
- **Çok adımlı görevlerde** ekranın görüntüsü Gemini'ye gönderilir. O anda ekranda kişisel bir bilgi açıksa o da gider — görsel görevlerden önce ekranı kontrol edin.
- Jarvis **silme, satın alma, ödeme, abone olma, şifre ve oturum kapatma** düğmelerine tıklamayı reddeder.
- **Terminal, Ayarlar ve Yazılım Merkezi** sesle açılmaz (bir öğrencinin bağırdığı cümle komuta dönüşmesin diye).
- Fare kontrolünde **acil durdurma**: fareyi ekranın herhangi bir **köşesine** götürün; Jarvis hemen durur. Sesle "İptal" de çalışır.
- Ekrandaki yazılar Jarvis için asla komut değildir; plan, sizin isteğinizden önceden çıkarılır.
- Konuşma geçmişi `data/jarvis_memory.json` dosyasında, yalnızca bu bilgisayarda tutulur.

---

## Proje yapısı

```
JARVİS/
├── server.py            Flask sunucusu (127.0.0.1:4700)
├── brain.py             Beyin: Groq/Gemini/Hugging Face çağrıları, komutlar, makbuzlar
├── ears.py              Dinleme: Groq Whisper
├── controller.py        Fare, klavye, ekran görüntüsü, uygulama/pencere kontrolü
├── daemon.py            "Hey Jarvis" / "Tahta" arka plan servisi
├── build.py             notes/ → bilgi galaksisi verisi
├── preflight.py         Tüm sistemi deneyen kontrol betiği
├── viewer/              Arayüz (index.html, galaxy.html, voice.js …)
├── notes/               Sizin notlarınız (.md)
├── textbooks/           Ders kitapları
├── captures/            "Hatırla …" ile kaydedilen notlar (GitHub'a yüklenmez)
├── data/                Konuşma geçmişi ve günlükler (GitHub'a yüklenmez)
├── config.json          API anahtarları ve ayarlar (GitHub'a yüklenmez)
├── jarvis-baslat.sh/.bat  Başlat
└── jarvis-durdur.sh/.bat  Durdur
```
