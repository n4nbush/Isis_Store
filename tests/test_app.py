import os
import tempfile
import unittest

import app as app_module


class IsisStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        app_module.DATABASE = self.db_path
        app_module.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = app_module.app.test_client()
        with app_module.app.app_context():
            app_module.init_db()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def login(self, username="admin", passwd="admin"):
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-token"
        return self.client.post(
            "/login",
            data={"username": username, "password": passwd, "csrf_token": "test-token"},
        )

    def test_login_and_home(self):
        response = self.login()
        self.assertEqual(response.status_code, 302)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Hola, admin", response.data)

    def test_admin_can_create_and_sell_product(self):
        self.login()
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-token"
        response = self.client.post(
            "/products/new",
            data={
                "name": "Remera",
                "size": "M",
                "stock": "10",
                "supplier_price": "100",
                "sale_price": "180",
                "csrf_token": "test-token",
            },
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.get("/products")
        self.assertIn(b"M", response.data)
        response = self.client.post(
            "/sales/new",
            data={"product_id": "1", "quantity": "3", "csrf_token": "test-token"},
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.get("/dashboard")
        self.assertIn(b"240.00", response.data)
        self.assertIn(b"Remera", response.data)

    def test_admin_can_delete_product(self):
        self.login()
        self.client.post(
            "/products/new",
            data={
                "name": "Camisa",
                "size": "S",
                "stock": "4",
                "supplier_price": "50",
                "sale_price": "90",
                "csrf_token": "test-token",
            },
        )
        response = self.client.post(
            "/products/1/delete", data={"csrf_token": "test-token"}
        )
        self.assertEqual(response.status_code, 302)

    def test_admin_can_create_and_delete_user(self):
        self.login()
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-token"
        response = self.client.post(
            "/users",
            data={
                "username": "vendedor",
                "password": "secreto",
                "role": "user",
                "csrf_token": "test-token",
            },
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.get("/users")
        self.assertIn(b"vendedor", response.data)
        response = self.client.post(
            "/users/2/delete", data={"csrf_token": "test-token"}
        )
        self.assertEqual(response.status_code, 302)


if __name__ == "__main__":
    unittest.main()
