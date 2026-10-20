from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from scripts import iniciar


class InicioTests(SimpleTestCase):
    def setUp(self):
        directorio = TemporaryDirectory()
        self.addCleanup(directorio.cleanup)
        self.root = Path(directorio.name)
        self.css = self.root / "theme/static/css/dist/styles.css"
        self.salida = self.enterContext(redirect_stdout(StringIO()))
        self.enterContext(patch("scripts.iniciar.find_spec", return_value=object()))

    def escribir_css(self):
        self.css.parent.mkdir(parents=True, exist_ok=True)
        self.css.write_text("body{color:white}", encoding="utf-8")

    def preparar_con_css(self):
        def ejecutar(comando, **opciones):
            if comando[-2:] == ["tailwind", "build"]:
                self.escribir_css()
        with patch("scripts.iniciar.subprocess.run", side_effect=ejecutar) as run:
            iniciar.preparar(self.root)
        return run

    def test_compila_css_ausente_antes_de_arrancar(self):
        run = self.preparar_con_css()
        self.assertTrue(self.css.is_file())
        self.assertEqual([c.args[0][2:] for c in run.call_args_list], [
            ["check", "--database", "default"], ["migrate", "--check"], ["tailwind", "build"],
        ])
        for llamada in run.call_args_list:
            self.assertEqual(llamada.args[0][:2], [sys.executable, "manage.py"])
            self.assertEqual(llamada.kwargs, {"cwd": self.root, "check": True})

    def test_css_vacio_tambien_se_regenera(self):
        self.escribir_css()
        self.css.write_bytes(b"")
        self.preparar_con_css()
        self.assertGreater(self.css.stat().st_size, 0)

    def test_css_existente_no_requiere_compilacion_inicial(self):
        self.escribir_css()
        with patch("scripts.iniciar.subprocess.run") as run:
            iniciar.preparar(self.root)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(self.css.read_text(), "body{color:white}")

    def test_dependencias_ausentes_indican_como_instalarlas(self):
        with patch("scripts.iniciar.find_spec", return_value=None), patch("scripts.iniciar.subprocess.run") as run:
            with self.assertRaisesRegex(SystemExit, "pip install -r requirements.txt"):
                iniciar.preparar(self.root)
        run.assert_not_called()

    def test_fallo_de_compilacion_indica_solucion(self):
        error = subprocess.CalledProcessError(1, ["tailwind", "build"])
        with patch("scripts.iniciar.subprocess.run", side_effect=[None, None, error]):
            with self.assertRaisesRegex(SystemExit, "python manage.py tailwind build"):
                iniciar.preparar(self.root)

    def test_compilador_sin_archivo_resultante_no_inicia_sitio_sin_estilos(self):
        with patch("scripts.iniciar.subprocess.run"):
            with self.assertRaisesRegex(SystemExit, "No se generaron los estilos"):
                iniciar.preparar(self.root)

    def test_base_inaccesible_o_migraciones_pendientes_indican_solucion(self):
        error = subprocess.CalledProcessError(1, ["migrate", "--check"])
        with patch("scripts.iniciar.subprocess.run", side_effect=[None, error]) as run:
            with self.assertRaisesRegex(SystemExit, "python manage.py migrate"):
                iniciar.preparar(self.root)
        self.assertEqual(run.call_count, 2)

    def test_configuracion_invalida_indica_env_sin_iniciar_procesos(self):
        error = subprocess.CalledProcessError(1, ["check"])
        with patch("scripts.iniciar.subprocess.run", side_effect=error), patch("scripts.iniciar.subprocess.Popen") as popen:
            with self.assertRaisesRegex(SystemExit, "preparar_entorno.py"):
                iniciar.main()
        popen.assert_not_called()


class ConfiguracionNuevaTests(SimpleTestCase):
    def test_genera_configuracion_sandbox_y_conserva_env_existente(self):
        with TemporaryDirectory() as carpeta:
            root = Path(carpeta)
            (root / "scripts").mkdir()
            for nombre in ("scripts/preparar_entorno.py", ".env.example"):
                shutil.copyfile(settings.BASE_DIR / nombre, root / nombre)
            comando = [sys.executable, str(root / "scripts/preparar_entorno.py")]
            primera = subprocess.run(comando, cwd=root, capture_output=True, text=True)
            self.assertEqual(primera.returncode, 0, primera.stderr)
            contenido = (root / ".env").read_bytes()
            valores = dict(line.split("=", 1) for line in contenido.decode().splitlines())
            for clave in ("SECRET_KEY", "DB_PASSWORD", "DEMO_PASSWORD"):
                self.assertGreaterEqual(len(valores[clave]), 48)
                self.assertNotIn(valores[clave], primera.stdout + primera.stderr)
            self.assertEqual(valores["PAYPAL_MODE"], "sandbox")
            self.assertEqual(valores["PAYPAL_CLIENT_SECRET"], "")
            segunda = subprocess.run(comando, cwd=root, capture_output=True, text=True)
            self.assertNotEqual(segunda.returncode, 0)
            self.assertEqual((root / ".env").read_bytes(), contenido)
