f=open("bybit_staking/ui/main_window.py","r",encoding="utf-8")
ls=f.readlines()
f.close()
ls[1226:1230]=["        except Exception as e:\n","            err_msg = str(e)\n","            if "Expected str" not in err_msg and "incorrect type" not in err_msg:\n","                if hasattr(self._main_window, "_debug_log"):\n","                    self._main_window._debug_log(f"{action}抵押品失败: {err_msg[:100]}")\n","                messagebox.showerror("失败", "{0}抵押品失败: {1}".format(action, err_msg[:100]), parent=self)\n","            return\n"]
f=open("bybit_staking/ui/main_window.py","w",encoding="utf-8")
f.writelines(ls)
f.close()
print("Done")